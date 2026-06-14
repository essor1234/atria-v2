"""DeepAnalyzeEngine — holds job registry + LLM client + ctx."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

from atria.core.skill_tools import SkillToolContext

from .jobs import AnalyzeJob, AnalyzeJobRegistry
from .pipeline import run_job
from .planning import run_planning
from .synthesis import synthesize_executive_summary, synthesize_key_findings, synthesize_section
from .validation import validate_input


def _format_profile_summary(file_name: str, job_id: str, profile: Dict[str, Any], error: Any) -> str:
    """Build a rich dataset summary for the agent to use as its opening response."""
    if error:
        return f"Analysis of `{file_name}` failed during load/profile: {error}"

    if not profile:
        return (
            f"Analysis of `{file_name}` is running (job `{job_id}`). "
            "Profile not yet available — progress streams live in chat."
        )

    row_count = profile.get("row_count", "?")
    cols = profile.get("columns", [])
    col_count = len(cols)

    # Top columns with key stats
    col_lines: List[str] = []
    for col in cols[:15]:
        dtype = col.get("dtype", "?")
        name = col.get("name", "?")
        if dtype in {"int", "float"}:
            parts = []
            if col.get("mean") is not None:
                parts.append(f"mean={col['mean']:.2f}")
            if col.get("min") is not None and col.get("max") is not None:
                parts.append(f"range=[{col['min']:.2f}, {col['max']:.2f}]")
            if col.get("nulls"):
                parts.append(f"nulls={col['nulls']}")
            col_lines.append(f"  - {name} ({dtype}): {', '.join(parts)}")
        else:
            top = col.get("top_values", [])[:3]
            top_str = ", ".join(f"{v['value']}({v['count']})" for v in top) if top else "—"
            col_lines.append(f"  - {name} ({dtype}): top={top_str}")

    # Notable correlations
    corr_lines: List[str] = []
    for c in profile.get("correlations", []):
        if c.get("notable"):
            corr_lines.append(f"  - {c['col_a']} ↔ {c['col_b']} (r={c.get('r', '?'):.2f})")

    lines = [
        f"Analysis of `{file_name}` started (job `{job_id}`).",
        f"Dataset: {row_count:,} rows × {col_count} columns.",
        "",
        "Column overview:",
        *col_lines,
    ]
    if col_count > 15:
        lines.append(f"  ... and {col_count - 15} more columns.")
    if corr_lines:
        lines += ["", "Notable correlations:", *corr_lines]
    lines += ["", "Analysis is running in the background — charts and insights will stream into the chat as each phase completes."]
    return "\n".join(lines)


class DeepAnalyzeEngine:
    def __init__(self, ctx: SkillToolContext) -> None:
        self._ctx = ctx
        self._registry = AnalyzeJobRegistry()
        self._fallback_root = Path.home() / ".atria" / "sessions"

    def _job_root(self, session_id: str) -> Path:
        wd = self._ctx.working_dir
        if wd:
            return Path(wd) / "analyze"
        return self._fallback_root / session_id / "analyze"

    def _client(self):
        from openai import OpenAI  # noqa: PLC0415

        return OpenAI(
            api_key=os.environ.get("DEEP_RESEARCH_API_KEY", "")
            or os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("DEEP_RESEARCH_BASE_URL", "https://api.openai.com/v1"),
        )

    def _chat(self, system: str, user: str) -> str:
        if self._ctx.llm_chat is not None:
            return self._ctx.llm_chat(system, user)
        resp = self._client().chat.completions.create(
            model=os.environ.get("DEEP_RESEARCH_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    def deep_analyze(self, file_path: str, session_id: str = "default", domain_context: str = "", depth: str = "standard") -> Dict[str, Any]:
        try:
            validated = validate_input(file_path)
            job_id = uuid.uuid4().hex[:12]
            job_dir = self._job_root(session_id) / job_id
            (job_dir / "charts").mkdir(parents=True, exist_ok=True)
            job = AnalyzeJob(
                job_id=job_id,
                session_id=session_id,
                file_path=str(validated),
                dir=job_dir,
                domain_context=domain_context,
                depth=depth,
            )

            def enricher(topic: str, context: str) -> Dict[str, Any]:
                from atria.skills.builtin.domain_enrich import engine as enrich_engine  # noqa: PLC0415
                return enrich_engine.run_enrich(
                    topic=topic,
                    context=context,
                    chat_fn=self._chat,
                    working_dir=str(job.dir),
                    on_artifact=self._ctx.on_artifact,
                )

            def planner(profile: Dict[str, Any]) -> Dict[str, Any]:
                return run_planning(profile, domain_brief=job.domain_brief, chat=self._chat, depth=job.depth)

            dispatcher = self._ctx.subagent_dispatcher

            def extractor(job_: AnalyzeJob, spec: Dict[str, Any]) -> None:
                if dispatcher is None:
                    return
                dispatcher(
                    agent="Data-Extractor",
                    task=(
                        f"Materialize sub-table `{spec['name']}` in the SQLite DB at "
                        f"{job_.dir / 'data.db'}. Planner SQL:\n\n{spec['sql']}\n\n"
                        f"Goal: {spec.get('why', '')}"
                    ),
                )

            def plan_modifier(plan: Dict[str, Any], instructions: str) -> Dict[str, Any]:
                from atria.skills.builtin.deep_analyze.planning import modify_plan  # noqa: PLC0415
                return modify_plan(plan, instructions, self._chat)

            def synthesizer(
                section: Dict[str, Any], stats_evidence: str, chart_insights: List[str]
            ) -> str:
                return synthesize_section(
                    section_name=section["name"],
                    description=section.get("description", ""),
                    angles=section.get("analysis_angles", []),
                    stats_evidence=stats_evidence,
                    chart_insights=chart_insights,
                    domain_brief=job.domain_brief,
                    chat_fn=self._chat,
                )

            def post_synthesizer(job_: AnalyzeJob) -> Tuple[str, str]:
                section_contents = [
                    {"name": s["name"], "content": s.get("content") or ""}
                    for s in job_.sections
                ]
                kf = synthesize_key_findings(section_contents, self._chat, domain_brief=job_.domain_brief)
                es = synthesize_executive_summary(
                    Path(job_.file_path).name,
                    section_contents,
                    kf,
                    self._chat,
                    domain_brief=job_.domain_brief,
                )
                return kf, es

            _chat_fn = self._chat
            self._registry.submit(
                job,
                lambda j: run_job(
                    self._ctx,
                    self._registry,
                    j,
                    planner=planner,
                    extractor=extractor,
                    synthesizer=synthesizer,
                    post_synthesizer=post_synthesizer,
                    chat_fn=_chat_fn,
                    reporter=None,
                    enricher=enricher,
                    plan_modifier=plan_modifier,
                ),
            )
            if self._ctx.broadcaster:
                self._ctx.broadcaster(
                    {"type": "analyze.started", "job_id": job_id, "file_name": validated.name}
                )

            # Wait for load+profile to finish (up to 90s) so we can give the
            # agent real dataset stats to work with instead of a placeholder.
            profile_ready = job._profile_ready.wait(timeout=90)
            profile = job.profile_rich if profile_ready else {}
            summary = _format_profile_summary(validated.name, job_id, profile, job.error)
            return {
                "success": True,
                "output": summary,
                "job_id": job_id,
                "_bg_task_started": True,
                "error": None,
            }
        except Exception as e:
            return {"success": False, "output": str(e), "error": str(e)}

    def get_analyze_status(self, job_id: str) -> Dict[str, Any]:
        job = self._registry.get(job_id)
        if job is None:
            return {"success": False, "output": "unknown job_id", "error": "unknown job_id"}
        details = {
            "status": job.status,
            "domain_brief_available": bool(job.domain_brief),
            "sub_tables": job.sub_tables,
            "charts": [
                {"name": c["name"], "png_path": c["png_path"], "insight_md": c["insight_md"]}
                for c in job.charts
            ],
            "sections": [
                {"name": s["name"], "has_content": bool(s.get("content"))} for s in job.sections
            ],
            "report_path": job.report_path,
            "error": job.error,
        }
        summary = (
            f"job {job_id}: status={job.status}, "
            f"sub_tables={len(job.sub_tables)}, charts={len(job.charts)}, "
            f"sections={len(job.sections)}"
            + (f", report={job.report_path}" if job.report_path else "")
            + (f", error={job.error}" if job.error else "")
        )
        return {"success": True, "output": summary, "details": details, "error": None}

    def cancel_analyze(self, job_id: str) -> Dict[str, Any]:
        job = self._registry.get(job_id)
        ok = False
        if job is not None and job.status not in {"done", "failed", "cancelled"}:
            job.cancel_event.set()
            ok = True
        return {"success": True, "output": f"cancelled={ok}", "cancelled": ok, "error": None}
