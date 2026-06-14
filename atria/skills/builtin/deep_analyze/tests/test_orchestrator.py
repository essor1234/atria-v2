"""Orchestrator: phase ordering, parallel fan-out, cancellation, failures."""

import sqlite3
import threading
import uuid
from pathlib import Path

import pytest

from atria.core.skill_tools import SkillToolContext
from atria.skills.builtin.deep_analyze.jobs import AnalyzeJob, AnalyzeJobRegistry
from atria.skills.builtin.deep_analyze.pipeline import run_job
from atria.skills.builtin.deep_analyze.planning import PlanningError


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "sales.csv"
    p.write_text("region,r\nNA,100\nEU,80\nAPAC,200\n")
    return p


def _plan() -> dict:
    return {
        "summary": "s",
        "sections": [
            {
                "name": "Revenue Overview",
                "description": "How revenue varies by region.",
                "chart_names": ["regional"],
                "analysis_angles": ["total revenue", "regional mix"],
            }
        ],
        "sub_tables": [
            {
                "name": "by_region",
                "sql": "CREATE TABLE t_by_region AS SELECT region, SUM(r) r FROM raw GROUP BY region",
                "why": "",
            },
        ],
        "charts": [
            {
                "name": "regional",
                "source_table": "t_by_region",
                "type": "bar",
                "x": "region",
                "y": ["r"],
                "title": "Regional",
            },
        ],
    }


def _make_job(tmp_path: Path, session_id: str, csv_file: Path) -> AnalyzeJob:
    job_id = uuid.uuid4().hex[:12]
    job_dir = tmp_path / session_id / "analyze" / job_id
    (job_dir / "charts").mkdir(parents=True, exist_ok=True)
    return AnalyzeJob(
        job_id=job_id,
        session_id=session_id,
        file_path=str(csv_file),
        dir=job_dir,
    )


def _run_blocking(
    job: AnalyzeJob,
    registry: AnalyzeJobRegistry,
    ctx: SkillToolContext,
    *,
    planner,
    extractor=lambda job, spec: None,
    synthesizer=lambda section, stats, charts: f"Narrative for {section['name']}",
    post_synthesizer=lambda job: ("- Finding 1", "Executive summary."),
    chat_fn=lambda system, user: '{"confidence": 1.0}',
    reporter=None,
    enricher=None,
    plan_modifier=None,
    timeout: float = 30,
) -> None:
    registry.submit(
        job,
        lambda j: run_job(
            ctx,
            registry,
            j,
            planner=planner,
            extractor=extractor,
            synthesizer=synthesizer,
            post_synthesizer=post_synthesizer,
            chat_fn=chat_fn,
            reporter=reporter,
            enricher=enricher,
            plan_modifier=plan_modifier,
        ),
    )
    job._done_event.wait(timeout=timeout)


def test_happy_path(csv_file: Path, tmp_path: Path) -> None:
    events: list[dict] = []
    ctx = SkillToolContext(broadcaster=lambda e: events.append(e))
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s1", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.status == "done"
    phases = [
        e["phase"] for e in events if e.get("type") == "analyze.phase" and e.get("status") == "done"
    ]
    assert phases == ["load", "profile", "explore", "plan", "extract", "synthesize", "report"]
    with sqlite3.connect(job.dir / "data.db") as cx:
        assert cx.execute("SELECT COUNT(*) FROM t_by_region").fetchone()[0] == 3


def test_sections_populated_after_planning(csv_file: Path, tmp_path: Path) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_sec", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.status == "done"
    assert len(job.sections) == 1
    assert job.sections[0]["name"] == "Revenue Overview"
    assert job.sections[0].get("content") == "Narrative for Revenue Overview"


def test_exec_summary_and_findings_populated(csv_file: Path, tmp_path: Path) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_es", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        post_synthesizer=lambda j: ("- Finding A", "Exec summary text."),
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.key_findings == "- Finding A"
    assert job.exec_summary == "Exec summary text."


def test_subtable_failure_does_not_abort_job(csv_file: Path, tmp_path: Path) -> None:
    bad_plan = _plan()
    bad_plan["sub_tables"].append(
        {"name": "broken", "sql": "CREATE TABLE t_broken AS SELECT nonsense FROM raw", "why": ""}
    )
    bad_plan["charts"].append(
        {
            "name": "broken_chart",
            "source_table": "t_broken",
            "type": "bar",
            "x": "region",
            "y": ["r"],
            "title": "x",
        }
    )
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s2", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: bad_plan,
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.status == "done"
    assert any(s["status"] == "failed" for s in job.sub_tables)
    assert any(s["status"] == "done" for s in job.sub_tables)


def test_cancel_before_render(csv_file: Path, tmp_path: Path) -> None:
    gate = threading.Event()

    def slow_extractor(job, spec):
        gate.wait(timeout=5)

    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s3", csv_file)
    registry.submit(
        job,
        lambda j: run_job(
            ctx,
            registry,
            j,
            planner=lambda profile: _plan(),
            extractor=slow_extractor,
            synthesizer=lambda s, ev, ci: "narrative",
            post_synthesizer=lambda j: ("findings", "summary"),
            chat_fn=lambda system, user: '{"confidence": 1.0}',
            reporter=lambda job: "x",
        ),
    )
    job.cancel_event.set()
    gate.set()
    job._done_event.wait(timeout=10)
    assert job.status == "cancelled"


def test_empty_plan_marks_failed(csv_file: Path, tmp_path: Path) -> None:
    def empty_planner(_profile):
        raise PlanningError("planner produced no work")

    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s4", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=empty_planner,
        reporter=lambda job: "x",
        timeout=10,
    )

    assert job.status == "failed"
    assert "no work" in (job.error or "")


@pytest.mark.skipif(
    True,
    reason="default reporter uses MdToPdfTool which requires pango/cairo native libs",
)
def test_default_reporter_produces_pdf(csv_file: Path, tmp_path: Path) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s5", csv_file)
    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        insighter=lambda job, png: "insight",
        reporter=None,
    )
    assert job.status == "done"
    assert job.report_path and Path(job.report_path).exists()
    assert Path(job.report_path).read_bytes()[:4] == b"%PDF"


def test_domain_brief_populated_after_enrich(csv_file: Path, tmp_path: Path) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_enrich", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        enricher=lambda topic, context: {"summary": f"Domain brief for {topic}", "sources": []},
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.status == "done"
    assert job.domain_brief.startswith("Domain brief for sales")


def test_enricher_failure_does_not_abort_job(csv_file: Path, tmp_path: Path) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_enrich_fail", csv_file)

    def failing_enricher(topic: str, context: str) -> dict:
        raise RuntimeError("network failure")

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        enricher=failing_enricher,
        reporter=lambda job: str(job.dir / "report.pdf"),
    )

    assert job.status == "done"
    # EXPLORE falls back to a stub brief derived from filename + columns when
    # enricher fails so downstream prompts always have non-empty context.
    assert job.domain_brief.startswith("Dataset:")
    assert "region" in job.domain_brief


# ── EXPLORE phase tests ────────────────────────────────────────────────────────


def test_explore_phase_runs_clarify_loop_and_populates_domain_brief(
    csv_file: Path, tmp_path: Path
) -> None:
    captured_clarify_msgs: list[dict] = []
    enrich_calls = {"count": 0}

    def clarify_cb(job_id: str, request_id: str, payload: dict) -> dict:
        return {
            "answers": [
                {"id": q["id"], "answer": f"canned-{q['id']}"} for q in payload["questions"]
            ]
        }

    def on_clarify_message(payload: dict) -> None:
        captured_clarify_msgs.append(payload)

    def enricher(topic: str, context: str) -> dict:
        enrich_calls["count"] += 1
        return {"summary": f"brief v{enrich_calls['count']} for {topic}"}

    # chat_fn: any ambiguity-question call returns empty list (so only the 3
    # fixed intent questions go out in iteration 1), and confidence assessment
    # returns 0.95 so the loop exits after one iteration.
    import json as _json

    def chat_fn(system: str, user: str) -> str:
        if "Assess your confidence" in user:
            return _json.dumps({"confidence": 0.95, "reason": "clear"})
        return _json.dumps({"questions": []})

    events: list[dict] = []
    ctx = SkillToolContext(
        broadcaster=lambda e: events.append(e),
        clarify_callback=clarify_cb,
        on_clarify_message=on_clarify_message,
    )
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_explore", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        enricher=enricher,
        chat_fn=chat_fn,
        reporter=lambda j: str(j.dir / "report.pdf"),
    )

    assert job.status == "done"
    # 3 fixed intent questions persisted as records
    assert len(job.clarification_qa) == 3
    assert all(r["answer"].startswith("canned-") for r in job.clarification_qa)

    # enricher called at least twice: once before Q&A, once after answers refresh it
    assert enrich_calls["count"] >= 2
    assert job.domain_brief.startswith("brief v")

    # Three persisted message types: assistant-questions, user-answers, final-brief
    roles_and_kinds = [
        (m["role"], next((k for k in m["metadata"] if k.startswith("da_")), ""))
        for m in captured_clarify_msgs
    ]
    assert ("assistant", "da_clarify_questions") in roles_and_kinds
    assert ("user", "da_clarify_answers") in roles_and_kinds
    assert ("assistant", "da_domain_brief") in roles_and_kinds

    # Explore phase fired its start/done events
    explore_phases = [
        e for e in events if e.get("type") == "analyze.phase" and e.get("phase") == "explore"
    ]
    assert {p["status"] for p in explore_phases} == {"start", "done"}


def test_explore_phase_falls_back_when_clarify_callback_is_none(
    csv_file: Path, tmp_path: Path
) -> None:
    captured: list[dict] = []
    ctx = SkillToolContext(on_clarify_message=lambda p: captured.append(p))
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_explore_noninter", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        enricher=lambda topic, context: {"summary": "auto-brief"},
        reporter=lambda j: str(j.dir / "report.pdf"),
    )

    assert job.status == "done"
    assert job.domain_brief == "auto-brief"
    assert job.clarification_qa == []
    # Only the final domain-brief message is persisted, no Q&A round-trip.
    da_kinds = [next((k for k in m["metadata"] if k.startswith("da_")), "") for m in captured]
    assert da_kinds == ["da_domain_brief"]


def test_explore_phase_uses_filename_fallback_when_enricher_missing(
    csv_file: Path, tmp_path: Path
) -> None:
    ctx = SkillToolContext()
    registry = AnalyzeJobRegistry()
    job = _make_job(tmp_path, "s_explore_stub", csv_file)

    _run_blocking(
        job,
        registry,
        ctx,
        planner=lambda profile: _plan(),
        enricher=None,
        reporter=lambda j: str(j.dir / "report.pdf"),
    )

    assert job.status == "done"
    assert job.domain_brief.startswith("Dataset:")
    assert "region" in job.domain_brief
