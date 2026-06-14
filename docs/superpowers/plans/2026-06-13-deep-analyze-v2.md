# deep_analyze v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `depth` param, a plan review pause (user edits plan before execution), and replace PNG chart rendering with live data streaming via `analyze.chart_data` WS events.

**Architecture:** The plan review loop mirrors `deep_research`'s taxonomy review — `ctx.review_callback` blocks the worker thread while the UI waits, with a unified dispatcher routing by event type. Chart data is queried from SQLite after each sub-table extracts and broadcast as `analyze.chart_data`, rendered client-side by the existing `DataMessage` component. PNG render and vision insight phases are removed entirely.

**Tech Stack:** Python (asyncio, sqlite3, threading), FastAPI WebSocket, React/TypeScript/Zustand

---

## File Map

| File | Change |
|---|---|
| `atria/skills/builtin/deep_analyze/schemas.py` | Add `depth` param |
| `atria/skills/builtin/deep_analyze/jobs.py` | Add `depth: str` field |
| `atria/skills/builtin/deep_analyze/prompts.py` | Add depth scope block in planner system prompt |
| `atria/skills/builtin/deep_analyze/planning.py` | Add `modify_plan()`, pass `depth` to `build_planning_system` |
| `atria/skills/builtin/deep_analyze/engine.py` | Pass `depth` to job/planner; define `plan_modifier` closure |
| `atria/skills/builtin/deep_analyze/pipeline.py` | Add plan review loop; replace render+insight fan-outs with `_query_table_rows` + `analyze.chart_data` emit; add `plan_modifier` param to `run_job` |
| `atria/web/state.py` | Add `_pending_plan_reviews` dict + CRUD methods + `aresolve_plan_review` |
| `atria/web/web_ui_callback.py` | Add `request_plan_review()` and unified `request_review()` dispatcher |
| `atria/web/websocket.py` | Add `analyze_plan_response` message type handler |
| `atria/web/agent_executor.py` | Wire `skill_ctx.review_callback = web_ui_callback.request_review` |
| `web-ui/src/types/index.ts` | Update `DeepAnalyzePhase`, `Message`, add `da_plan*` fields, new WS event types |
| `web-ui/src/stores/chat.ts` | Handle `analyze.plan_ready`, `analyze.chart_data`; update `DA_PHASES`; remove `render`/`insight` handlers |
| `web-ui/src/components/Chat/DeepAnalyzeBlock.tsx` | Add `PlanReviewPanel`, remove insights/charts section, update PHASES list |

---

## Task 1: Depth param — schemas, jobs, prompts, engine

**Files:**
- Modify: `atria/skills/builtin/deep_analyze/schemas.py`
- Modify: `atria/skills/builtin/deep_analyze/jobs.py`
- Modify: `atria/skills/builtin/deep_analyze/prompts.py`
- Modify: `atria/skills/builtin/deep_analyze/engine.py`

- [ ] **Step 1: Add `depth` to `PARAMS_DEEP_ANALYZE` in `schemas.py`**

Replace the existing `PARAMS_DEEP_ANALYZE` dict with:

```python
PARAMS_DEEP_ANALYZE = {
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Absolute path to a .csv or .xlsx file.",
        },
        "domain_context": {
            "type": "string",
            "description": (
                "Optional framing for domain enrichment "
                "(e.g. 'workforce automation 2030'). "
                "If omitted, the topic is inferred from the filename."
            ),
            "default": "",
        },
        "depth": {
            "type": "string",
            "enum": ["fast", "standard", "deep"],
            "description": (
                "Analysis depth. 'fast' = 2 sections & 3 charts, "
                "'standard' = 3-4 sections & 4 charts (default), "
                "'deep' = 5 sections & 6 charts."
            ),
            "default": "standard",
        },
    },
    "required": ["file_path"],
}
```

- [ ] **Step 2: Add `depth` field to `AnalyzeJob` in `jobs.py`**

Add `depth: str = "standard"` after the `domain_context` field:

```python
@dataclass
class AnalyzeJob:
    job_id: str
    session_id: str
    file_path: str
    dir: Path
    status: str = "pending"
    error: Optional[str] = None
    profile: Dict[str, Any] = field(default_factory=dict)
    profile_rich: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    sub_tables: List[Dict[str, Any]] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)
    sections: List[Dict[str, Any]] = field(default_factory=list)
    exec_summary: Optional[str] = None
    key_findings: Optional[str] = None
    domain_brief: str = ""
    domain_context: str = ""
    depth: str = "standard"
    report_path: Optional[str] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _done_event: threading.Event = field(default_factory=threading.Event)
```

- [ ] **Step 3: Add depth scope block to `build_planning_system` in `prompts.py`**

```python
_DEPTH_SCOPE = {
    "fast":     "Propose exactly 2 sections, 3 sub_tables, and 2-3 charts total.",
    "standard": "Propose 3-4 sections, 4-5 sub_tables, and 4 charts total.",
    "deep":     "Propose 5 sections, 6 sub_tables, and 6 charts total.",
}


def build_planning_system(domain_brief: str = "", depth: str = "standard") -> str:
    scope = _DEPTH_SCOPE.get(depth, _DEPTH_SCOPE["standard"])
    depth_block = f"\nScope: {scope}\n"
    base = _PLANNING_SYSTEM_BASE + depth_block
    if not domain_brief:
        return base
    domain_block = (
        f"\nDomain context (use this vocabulary and framing when naming sections "
        f"and choosing analysis angles):\n{domain_brief}\n"
    )
    return base + domain_block
```

- [ ] **Step 4: Wire `depth` in `engine.py`**

In `deep_analyze()`, add `depth: str = "standard"` param:

```python
def deep_analyze(self, file_path: str, session_id: str = "default", domain_context: str = "", depth: str = "standard") -> Dict[str, Any]:
```

Pass `depth` to `AnalyzeJob`:

```python
job = AnalyzeJob(
    job_id=job_id,
    session_id=session_id,
    file_path=str(validated),
    dir=job_dir,
    domain_context=domain_context,
    depth=depth,
)
```

Update the `planner` closure to pass `depth`:

```python
def planner(profile: Dict[str, Any]) -> Dict[str, Any]:
    return run_planning(profile, domain_brief=job.domain_brief, chat=self._chat, depth=job.depth)
```

- [ ] **Step 5: Update `run_planning` signature in `planning.py`**

Add `depth: str = "standard"` param and pass it to `build_planning_system`:

```python
def run_planning(
    profile: Dict[str, Any],
    chat: Callable[[str, str], str],
    domain_brief: str = "",
    depth: str = "standard",
) -> Dict[str, Any]:
    system = build_planning_system(domain_brief, depth)
    ...  # rest unchanged
```

- [ ] **Step 6: Commit**

```bash
git add atria/skills/builtin/deep_analyze/schemas.py \
        atria/skills/builtin/deep_analyze/jobs.py \
        atria/skills/builtin/deep_analyze/prompts.py \
        atria/skills/builtin/deep_analyze/planning.py \
        atria/skills/builtin/deep_analyze/engine.py
git commit -m "feat(deep_analyze): add depth param fast/standard/deep"
```

---

## Task 2: `modify_plan()` function

**Files:**
- Modify: `atria/skills/builtin/deep_analyze/planning.py`

- [ ] **Step 1: Write failing test in `tests/test_modify_plan.py`**

Create `atria/skills/builtin/deep_analyze/tests/test_modify_plan.py`:

```python
"""Tests for modify_plan()."""
import json
import pytest
from atria.skills.builtin.deep_analyze.planning import modify_plan

_BASE_PLAN = {
    "summary": "Test dataset",
    "sections": [{"name": "Sec A", "description": "d", "chart_names": ["c1"], "analysis_angles": []}],
    "sub_tables": [{"name": "tbl1", "sql": "CREATE TABLE t_tbl1 AS SELECT * FROM raw", "why": "w"}],
    "charts": [{"name": "c1", "source_table": "t_tbl1", "type": "bar", "x": "col1", "y": ["col2"], "title": "T"}],
}


def test_modify_plan_returns_valid_plan():
    """modify_plan should return a dict with sections, sub_tables, charts."""
    def fake_chat(system: str, user: str) -> str:
        return json.dumps(_BASE_PLAN)

    result = modify_plan(_BASE_PLAN, "add a pie chart", fake_chat)
    assert "sections" in result
    assert "sub_tables" in result
    assert "charts" in result


def test_modify_plan_falls_back_on_parse_failure():
    """modify_plan should return original plan if LLM output is unparseable."""
    def bad_chat(system: str, user: str) -> str:
        return "not json at all"

    result = modify_plan(_BASE_PLAN, "do something", bad_chat)
    assert result == _BASE_PLAN
```

- [ ] **Step 2: Run test to confirm failure**

```bash
uv run pytest atria/skills/builtin/deep_analyze/tests/test_modify_plan.py -v
```

Expected: `ImportError` or `AttributeError` — `modify_plan` not yet defined.

- [ ] **Step 3: Implement `modify_plan()` in `planning.py`**

Add after the existing `run_planning` function:

```python
_MODIFY_SYSTEM = (
    "You are a data-analysis planner. The user has an existing analysis plan and wants "
    "to modify it. Apply their instructions and return ONLY the updated plan as valid JSON "
    "with the same structure: {summary, sections, sub_tables, charts}. "
    "Follow the same rules as before: sub_tables must SELECT only from `raw`, "
    "chart types must be bar/line/scatter/hist/pie, all referenced columns must exist. "
    "Return ONLY valid JSON — no prose, no markdown fences."
)


def modify_plan(
    plan: Dict[str, Any],
    instructions: str,
    chat: Callable[[str, str], str],
) -> Dict[str, Any]:
    """Apply user modification instructions to an existing plan via LLM.

    Falls back to the original plan on parse failure.
    """
    user = (
        f"Current plan:\n{json.dumps(_sanitize(plan), ensure_ascii=False)}\n\n"
        f"Modification request: {instructions}"
    )
    try:
        raw = chat(_MODIFY_SYSTEM, user)
        return _parse_plan(raw)
    except Exception as e:
        logger.warning("modify_plan failed (%s) — keeping original plan", e)
        return plan
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest atria/skills/builtin/deep_analyze/tests/test_modify_plan.py -v
```

Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/skills/builtin/deep_analyze/planning.py \
        atria/skills/builtin/deep_analyze/tests/test_modify_plan.py
git commit -m "feat(deep_analyze): add modify_plan() for plan review loop"
```

---

## Task 3: Plan review state + web wiring

**Files:**
- Modify: `atria/web/state.py`
- Modify: `atria/web/web_ui_callback.py`
- Modify: `atria/web/websocket.py`
- Modify: `atria/web/agent_executor.py`

- [ ] **Step 1: Add plan review state bucket to `state.py`**

In `AppState.__init__`, after `self._pending_taxonomy_reviews`:

```python
# Pending deep_analyze plan review requests
self._pending_plan_reviews: Dict[str, Dict[str, Any]] = {}
```

Add these four methods after `clear_taxonomy_review()` (around line 474):

```python
# --- Plan review state ---

def add_pending_plan_review(
    self,
    request_id: str,
    data: Dict[str, Any],
    session_id: Optional[str] = None,
    event: Optional[threading.Event] = None,
) -> None:
    with self._lock:
        self._pending_plan_reviews[request_id] = {
            "data": data,
            "resolved": False,
            "action": None,
            "instructions": None,
            "session_id": session_id,
            "_event": event,
        }
    self._schedule_async(self._persist_pending("plan_review", request_id, session_id, data))

def resolve_plan_review(
    self,
    request_id: str,
    action: str = "accept",
    instructions: Optional[str] = None,
) -> bool:
    with self._lock:
        if request_id in self._pending_plan_reviews:
            self._pending_plan_reviews[request_id]["resolved"] = True
            self._pending_plan_reviews[request_id]["action"] = action
            self._pending_plan_reviews[request_id]["instructions"] = instructions
            event = self._pending_plan_reviews[request_id].get("_event")
            if event:
                event.set()
            return True
        return False

def get_pending_plan_review(self, request_id: str) -> Optional[Dict[str, Any]]:
    with self._lock:
        return self._pending_plan_reviews.get(request_id)

def clear_plan_review(self, request_id: str) -> None:
    with self._lock:
        self._pending_plan_reviews.pop(request_id, None)

async def aresolve_plan_review(
    self,
    request_id: str,
    action: str = "accept",
    instructions: Optional[str] = None,
) -> bool:
    ok = self.resolve_plan_review(request_id, action, instructions)
    response = {"action": action, "instructions": instructions}
    db_ok = await self._persist_resolution(request_id, response)
    return ok or db_ok
```

- [ ] **Step 2: Add `request_plan_review()` and unified `request_review()` to `web_ui_callback.py`**

Add after `request_taxonomy_review()` (after line 170):

```python
def request_plan_review(
    self,
    job_id: str,
    review_request_id: str,
    event_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Block until user accepts/modifies/regenerates the analysis plan."""
    done_event = threading.Event()

    self.state.add_pending_plan_review(
        review_request_id,
        {"job_id": job_id, "session_id": self.session_id},
        session_id=self.session_id,
        event=done_event,
    )

    if event_payload is not None:
        data = {k: v for k, v in event_payload.items() if k != "type"}
        data["session_id"] = self.session_id
        self._broadcast({"type": "analyze.plan_ready", "data": data})

    logger.info(f"Blocking for plan review: {review_request_id} / job {job_id}")

    if not done_event.wait(timeout=600):
        logger.warning(f"Plan review {review_request_id} timed out")
        self.state.clear_plan_review(review_request_id)
        return {"action": "accept"}

    pending = self.state.get_pending_plan_review(review_request_id)
    self.state.clear_plan_review(review_request_id)
    if not pending:
        return {"action": "accept"}

    action = pending.get("action", "accept")
    logger.info(f"Plan review {review_request_id} resolved: action={action}")
    return {
        "action": action,
        "instructions": pending.get("instructions"),
    }

def request_review(
    self,
    job_id: str,
    review_request_id: str,
    event_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Unified review callback — dispatches by event_payload type."""
    event_type = (event_payload or {}).get("type", "")
    if event_type == "analyze.plan_ready":
        return self.request_plan_review(job_id, review_request_id, event_payload)
    return self.request_taxonomy_review(job_id, review_request_id, event_payload)
```

- [ ] **Step 3: Add `analyze_plan_response` handler in `websocket.py`**

In `handle_message()`, add a new branch after the `deep_research_taxonomy_response` branch:

```python
elif msg_type == "analyze_plan_response":
    await self._handle_plan_review_response(websocket, data)
```

Add the handler method (after `_handle_taxonomy_response`):

```python
async def _handle_plan_review_response(self, websocket: WebSocket, data: Dict[str, Any]):
    """Handle an analyze plan review response from the web UI."""
    response_data = data.get("data", {})
    request_id = response_data.get("requestId")
    action = response_data.get("action", "accept")
    instructions = response_data.get("instructions", "")

    if not request_id:
        await self.send_message(
            websocket,
            {"type": WSMessageType.ERROR, "data": {"message": "Missing requestId"}},
        )
        return

    state = get_state()
    success = await state.aresolve_plan_review(request_id, action, instructions or None)

    if not success:
        await self.send_message(
            websocket,
            {"type": WSMessageType.ERROR, "data": {"message": f"Plan review {request_id} not found"}},
        )
        return

    logger.info(f"Plan review {request_id} resolved: action={action}")
```

- [ ] **Step 4: Update `agent_executor.py` to wire the unified callback**

Find the line (around line 310):
```python
skill_ctx.review_callback = web_ui_callback.request_taxonomy_review
```

Replace with:
```python
skill_ctx.review_callback = web_ui_callback.request_review
```

- [ ] **Step 5: Commit**

```bash
git add atria/web/state.py \
        atria/web/web_ui_callback.py \
        atria/web/websocket.py \
        atria/web/agent_executor.py
git commit -m "feat(deep_analyze): wire plan review state + WS handler + unified review callback"
```

---

## Task 4: Pipeline refactor — plan review loop + chart data streaming

**Files:**
- Modify: `atria/skills/builtin/deep_analyze/pipeline.py`
- Modify: `atria/skills/builtin/deep_analyze/engine.py`

- [ ] **Step 1: Add `plan_modifier` type alias and `_query_table_rows` helper to `pipeline.py`**

At the top of `pipeline.py`, add the new type alias after the existing ones:

```python
PlanModifierFn = Callable[[Dict[str, Any], str], Dict[str, Any]]
```

Add the `_query_table_rows` helper function before `run_job`:

```python
def _query_table_rows(db_path: Path, table_name: str, max_rows: int = 10_000) -> Dict[str, Any]:
    """Query all rows from a SQLite table, return typed columns + row dicts."""
    import sqlite3  # noqa: PLC0415

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(f"SELECT * FROM {table_name} LIMIT {max_rows}")  # noqa: S608
        col_names = [d[0] for d in cur.description] if cur.description else []
        rows_raw = cur.fetchall()

    rows: List[Dict[str, Any]] = [dict(zip(col_names, r)) for r in rows_raw]

    columns: List[Dict[str, str]] = []
    for col in col_names:
        values = [r.get(col) for r in rows]
        non_null = [v for v in values if v is not None]
        if non_null and all(isinstance(v, (int, float)) for v in non_null):
            col_type = "number"
        else:
            col_type = "string"
        columns.append({"name": col, "type": col_type})

    return {"columns": columns, "rows": rows}
```

- [ ] **Step 2: Update `run_job` signature — add `plan_modifier`, remove `visualizer` and `insighter`**

New signature:

```python
def run_job(
    ctx: SkillToolContext,
    registry: AnalyzeJobRegistry,
    job: AnalyzeJob,
    planner: PlannerFn,
    extractor: ExtractorFn,
    synthesizer: SynthesizerFn,
    post_synthesizer: PostSynthesizerFn,
    reporter: Optional[ReporterFn] = None,
    enricher: Optional[EnricherFn] = None,
    plan_modifier: Optional[PlanModifierFn] = None,
) -> None:
```

Remove `VisualizerFn` and `InsighterFn` from the imports at the top — update the type alias block:

```python
PlannerFn = Callable[[Dict[str, Any]], Dict[str, Any]]
ExtractorFn = Callable[[AnalyzeJob, Dict[str, Any]], None]
SynthesizerFn = Callable[[Dict[str, Any], str, List[str]], str]
PostSynthesizerFn = Callable[[AnalyzeJob], Tuple[str, str]]
ReporterFn = Callable[[AnalyzeJob], str]
EnricherFn = Callable[[str, str], Dict[str, Any]]
PlanModifierFn = Callable[[Dict[str, Any], str], Dict[str, Any]]
```

- [ ] **Step 3: Replace the pipeline body of `run_job`**

Replace the entire body of `run_job` (after the `try:`) with:

```python
    try:
        # ── enrich ───────────────────────────────────────────────────────────
        job.status = "enriching"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "enrich", "status": "start"})
        if enricher is not None:
            try:
                topic = _infer_topic(Path(job.file_path).name)
                result = enricher(topic, job.domain_context)
                job.domain_brief = result.get("summary", "") or ""
            except Exception as _enrich_err:
                logger.warning("domain enrichment failed (continuing): %s", _enrich_err)
                job.domain_brief = ""
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "enrich", "status": "done"})
        if _check_cancel(ctx, job):
            return

        # ── load ─────────────────────────────────────────────────────────────
        job.status = "loading"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "load", "status": "start"})
        rows = load_to_sqlite(Path(job.file_path), job.dir / "data.db")
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "load", "status": "done", "rows": rows})
        if _check_cancel(ctx, job):
            return

        # ── profile ───────────────────────────────────────────────────────────
        job.status = "profiling"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "profile", "status": "start"})
        job.profile_rich = build_rich_profile(job.dir / "data.db", file_name=Path(job.file_path).name)
        job.profile = job.profile_rich
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "profile", "status": "done"})
        if _check_cancel(ctx, job):
            return

        # ── plan ──────────────────────────────────────────────────────────────
        job.status = "planning"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "plan", "status": "start"})
        job.plan = planner(job.profile_rich)
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "plan", "status": "done",
                    "sub_tables": len(job.plan["sub_tables"]),
                    "charts": len(job.plan["charts"]),
                    "sections": len(job.plan.get("sections", []))})
        if _check_cancel(ctx, job):
            return

        # ── plan review (blocks until user accepts) ───────────────────────────
        if ctx.review_callback is not None:
            import uuid  # noqa: PLC0415
            while True:
                request_id = uuid.uuid4().hex[:12]
                result = ctx.review_callback(job.job_id, request_id, {
                    "type": "analyze.plan_ready",
                    "job_id": job.job_id,
                    "plan": job.plan,
                    "request_id": request_id,
                })
                action = result.get("action", "accept")
                if action == "modify" and plan_modifier is not None:
                    instructions = (result.get("instructions") or "").strip()
                    if instructions:
                        try:
                            job.plan = plan_modifier(job.plan, instructions)
                        except Exception as _mod_err:
                            logger.error("plan_modifier failed: %s — keeping previous plan", _mod_err)
                elif action == "regenerate":
                    try:
                        job.plan = planner(job.profile_rich)
                    except Exception as _regen_err:
                        logger.error("plan regeneration failed: %s — keeping previous plan", _regen_err)
                else:
                    break
                if _check_cancel(ctx, job):
                    return

        job.sections = [dict(s) for s in job.plan.get("sections", [])]

        # ── extract + stream chart data ───────────────────────────────────────
        job.status = "extracting"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "extract", "status": "start"})
        job.sub_tables = _fanout_extract(ctx, registry, job, extractor)
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "extract", "status": "done"})
        if _check_cancel(ctx, job):
            return

        # ── synthesize ────────────────────────────────────────────────────────
        job.status = "synthesizing"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "synthesize", "status": "start"})
        _fanout_synthesize(ctx, registry, job, synthesizer)
        key_findings, exec_summary = post_synthesizer(job)
        job.key_findings = key_findings
        job.exec_summary = exec_summary
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "synthesize", "status": "done"})
        if _check_cancel(ctx, job):
            return

        # ── report ────────────────────────────────────────────────────────────
        job.status = "reporting"
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "report", "status": "start"})
        fn = reporter or default_reporter
        job.report_path = fn(job)
        _emit(ctx, {"type": "analyze.phase", "job_id": job.job_id, "phase": "report", "status": "done"})
        _emit(ctx, {"type": "analyze.report", "job_id": job.job_id, "pdf_path": job.report_path})

        job.status = "done"
        _emit(ctx, {"type": "analyze.done", "job_id": job.job_id})

    except Exception as e:
        logger.exception("deep_analyze job failed: %s", e)
        failed_phase = job.status
        job.status = "failed"
        job.error = str(e)
        _emit(ctx, {"type": "analyze.failed", "job_id": job.job_id, "phase": failed_phase, "error": str(e)})
    finally:
        job._done_event.set()
```

- [ ] **Step 4: Update `_fanout_extract` to emit `analyze.chart_data` after each success**

Replace `_fanout_extract` with:

```python
def _fanout_extract(ctx, registry, job, extractor):
    results, futures = [], []
    for spec in job.plan["sub_tables"]:
        futures.append(registry.fanout.submit(_run_extract, job, spec, extractor))

    chart_by_table: Dict[str, List[Dict[str, Any]]] = {}
    for c in job.plan.get("charts", []):
        key = c["source_table"].removeprefix("t_")
        chart_by_table.setdefault(key, []).append(c)

    for spec, fut in zip(job.plan["sub_tables"], futures):
        try:
            rows = fut.result()
            results.append({"name": spec["name"], "rows": rows, "status": "done"})
            _emit(ctx, {"type": "analyze.subtable", "job_id": job.job_id,
                        "name": spec["name"], "rows": rows, "status": "done"})
            # Stream chart data for this table to the UI
            chart_specs = chart_by_table.get(spec["name"], [])
            if chart_specs:
                try:
                    table_data = _query_table_rows(job.dir / "data.db", f"t_{spec['name']}")
                    _emit(ctx, {
                        "type": "analyze.chart_data",
                        "job_id": job.job_id,
                        "name": spec["name"],
                        "title": chart_specs[0].get("title", spec["name"]),
                        "columns": table_data["columns"],
                        "rows": table_data["rows"],
                        "suggestions": [
                            {
                                "chart_type": c["type"],
                                "x": c["x"],
                                "y": c["y"] if isinstance(c["y"], list) else [c["y"]],
                                "title": c.get("title", ""),
                            }
                            for c in chart_specs
                        ],
                    })
                except Exception as _data_err:
                    logger.warning("chart_data emit for %s failed: %s", spec["name"], _data_err)
        except Exception as e:
            logger.warning("subtable %s failed: %s", spec["name"], e)
            results.append({"name": spec["name"], "rows": 0, "status": "failed", "error": str(e)})
            _emit(ctx, {"type": "analyze.subtable", "job_id": job.job_id,
                        "name": spec["name"], "rows": 0, "status": "failed", "error": str(e)})
    return results
```

- [ ] **Step 5: Remove `_fanout_render`, `_run_render`, `_fanout_insight` from `pipeline.py`**

Delete the following functions entirely:
- `_fanout_render`
- `_run_render`
- `_fanout_insight`

Also delete the `_build_stats_evidence` helper — it's only used by `_fanout_synthesize`. Check:

```bash
grep -n "_build_stats_evidence\|_fanout_render\|_run_render\|_fanout_insight" \
  atria/skills/builtin/deep_analyze/pipeline.py
```

Keep `_fanout_synthesize` — it already accepts an empty `chart_insights` list and works fine. Update `_fanout_synthesize` call site: pass empty list for `chart_insights` since there are no insight strings anymore:

In `_fanout_synthesize`, the `chart_lookup` lookup block becomes dead code. Simplify it:

```python
def _fanout_synthesize(ctx, registry, job, synthesizer):
    stats_evidence = _build_stats_evidence(job)
    futures = []
    for section in job.sections:
        futures.append(registry.fanout.submit(synthesizer, section, stats_evidence, []))

    for section, fut in zip(job.sections, futures):
        try:
            section["content"] = fut.result()
            _emit(ctx, {"type": "analyze.section_synthesized", "job_id": job.job_id,
                        "name": section["name"], "status": "done"})
        except Exception as e:
            logger.warning("synthesis %s failed: %s", section.get("name"), e)
            section["content"] = None
            _emit(ctx, {"type": "analyze.section_synthesized", "job_id": job.job_id,
                        "name": section.get("name"), "status": "failed", "error": str(e)})
```

Keep `_build_stats_evidence` — it's still needed for synthesis.

- [ ] **Step 6: Update `engine.py` — remove visualizer/insighter closures, add plan_modifier**

In `deep_analyze()`, remove the `visualizer` and `insighter` closures entirely. Add `plan_modifier`:

```python
def plan_modifier(plan: Dict[str, Any], instructions: str) -> Dict[str, Any]:
    from atria.skills.builtin.deep_analyze.planning import modify_plan  # noqa: PLC0415
    return modify_plan(plan, instructions, self._chat)
```

Update the `self._registry.submit(...)` call — remove `visualizer=visualizer, insighter=insighter`, add `plan_modifier=plan_modifier`:

```python
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
        reporter=None,
        enricher=enricher,
        plan_modifier=plan_modifier,
    ),
)
```

Also remove the `_vision_insight` method from `DeepAnalyzeEngine` — it's no longer called.

- [ ] **Step 7: Run existing analyze tests**

```bash
uv run pytest atria/skills/builtin/deep_analyze/tests/ -v
```

Expected: all existing tests PASS (they don't exercise the pipeline directly).

- [ ] **Step 8: Commit**

```bash
git add atria/skills/builtin/deep_analyze/pipeline.py \
        atria/skills/builtin/deep_analyze/engine.py
git commit -m "feat(deep_analyze): plan review loop + chart data streaming, remove PNG render phase"
```

---

## Task 5: Frontend types and store updates

**Files:**
- Modify: `web-ui/src/types/index.ts`
- Modify: `web-ui/src/stores/chat.ts`

- [ ] **Step 1: Update `DeepAnalyzePhase` type in `types/index.ts`**

Replace:
```ts
export type DeepAnalyzePhase = 'enrich' | 'load' | 'profile' | 'plan' | 'extract' | 'render' | 'insight' | 'report';
```

With:
```ts
export type DeepAnalyzePhase = 'enrich' | 'load' | 'profile' | 'plan' | 'extract' | 'synthesize' | 'report';
```

- [ ] **Step 2: Add plan review fields and update `da_status` in `Message` in `types/index.ts`**

Replace:
```ts
da_status?: 'running' | 'done' | 'error' | 'cancelled';
```

With:
```ts
da_status?: 'running' | 'plan_reviewing' | 'done' | 'error' | 'cancelled';
```

After `da_failed_phase?: string;`, add:
```ts
da_plan?: { sections: Array<{ name: string; chart_names: string[] }>; charts: any[]; sub_tables: any[] };
da_plan_review_request_id?: string;
```

- [ ] **Step 3: Add new WS event types to the union in `types/index.ts`**

Find the `type:` union string in the WS message interface (line 177). Add `'analyze.plan_ready'` and `'analyze.chart_data'` to the union:

```ts
  type: '...' | 'analyze.plan_ready' | 'analyze.chart_data';
```

- [ ] **Step 4: Remove `DeepAnalyzeChart` and `DeepAnalyzeInsight` from `types/index.ts`**

Delete the two interfaces (they are no longer used — charts are now `data_message` bubbles):

```ts
// DELETE these:
export interface DeepAnalyzeChart { ... }
export interface DeepAnalyzeInsight { ... }
```

Also remove `da_charts` and `da_insights` from `Message`:
```ts
// DELETE:
da_charts?: DeepAnalyzeChart[];
da_insights?: DeepAnalyzeInsight[];
```

- [ ] **Step 5: Update `DA_PHASES` constant and remove old chart/insight handlers in `stores/chat.ts`**

Find `DA_PHASES` (used in `analyze.phase` handler). Replace `'render' | 'insight'` phases. Search for:
```ts
const DA_PHASES
```

Update it to:
```ts
const DA_PHASES = ['enrich', 'load', 'profile', 'plan', 'extract', 'synthesize', 'report'] as const;
```

Delete the `wsClient.on('analyze.chart', ...)` handler entirely (around line 1239).

Delete the `wsClient.on('analyze.insight', ...)` handler entirely (around line 1251).

- [ ] **Step 6: Add `analyze.plan_ready` handler in `stores/chat.ts`**

Add after the `wsClient.on('analyze.phase', ...)` handler:

```ts
wsClient.on('analyze.plan_ready', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { job_id, plan, request_id } = message.data;
  if (!job_id) return;

  upsertDeepAnalyzeMessage(sid, job_id, prev => ({
    ...prev,
    da_status: 'plan_reviewing',
    da_plan: plan,
    da_plan_review_request_id: request_id,
  }));
});
```

- [ ] **Step 7: Add `analyze.chart_data` handler in `stores/chat.ts`**

Add after `analyze.plan_ready` handler:

```ts
wsClient.on('analyze.chart_data', (message) => {
  const sid = resolveSessionId(message.data);
  if (!sid) return;
  const { name, title, columns, rows, suggestions } = message.data;

  const dataMsg: Message = {
    role: 'data_message',
    content: title || name || '',
    data_message_id: `da_chart_${name}`,
    data_title: title || name || '',
    data_columns: columns,
    data_rows: rows,
    data_suggestions: suggestions,
    timestamp: new Date().toISOString(),
  };

  useChatStore.setState(state => {
    const ss = getSessionState(state.sessionStates, sid);
    return patchSession(state, sid, { messages: [...ss.messages, dataMsg] });
  });
});
```

- [ ] **Step 8: Build to verify no TypeScript errors**

```bash
cd web-ui && npm run build 2>&1 | tail -20
```

Expected: build completes with no type errors. Fix any remaining references to `da_charts`, `da_insights`, `DeepAnalyzeChart`, or `DeepAnalyzeInsight`.

- [ ] **Step 9: Commit**

```bash
git add web-ui/src/types/index.ts web-ui/src/stores/chat.ts
git commit -m "feat(frontend): update deep_analyze types, add plan_ready + chart_data handlers"
```

---

## Task 6: `DeepAnalyzeBlock` — plan review UI

**Files:**
- Modify: `web-ui/src/components/Chat/DeepAnalyzeBlock.tsx`

- [ ] **Step 1: Add `PlanReviewPanel` component inside `DeepAnalyzeBlock.tsx`**

Add the following component definition before `DeepAnalyzeBlock` (after imports):

```tsx
import { ArrowRight } from 'lucide-react';
import { wsClient } from '../../api/websocket';
```

(Add these to existing import lines — merge with existing lucide-react and wsClient imports.)

```tsx
// ─── Plan review panel ────────────────────────────────────────────────────────

function PlanReviewPanel({ message }: { message: Message }) {
  const { da_plan_review_request_id, da_plan, da_job_id } = message;
  const [instructions, setInstructions] = useState('');
  const [pending, setPending] = useState<'modify' | 'regenerate' | 'accept' | null>(null);

  const send = (action: 'modify' | 'regenerate' | 'accept') => {
    if (!da_plan_review_request_id || pending) return;
    if (action === 'modify' && !instructions.trim()) return;
    setPending(action);
    wsClient.send({
      type: 'analyze_plan_response',
      data: {
        requestId: da_plan_review_request_id,
        job_id: da_job_id,
        action,
        ...(action === 'modify' && { instructions: instructions.trim() }),
      },
    });
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send('modify'); }
  };

  const sections = da_plan?.sections ?? [];
  const chartCount = da_plan?.charts?.length ?? 0;
  const tableCount = da_plan?.sub_tables?.length ?? 0;

  return (
    <div className="p-4 space-y-4">
      {/* Plan summary */}
      {sections.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-text-400 font-mono">
            Analysis plan — {sections.length} sections · {chartCount} charts · {tableCount} sub-tables
          </p>
          <div className="space-y-1">
            {sections.map((sec, i) => (
              <div key={i} className="flex items-start gap-2 px-2 py-1 bg-bg-200/30 rounded text-xs font-mono">
                <span className="text-text-500 flex-shrink-0">{i + 1}.</span>
                <span className="text-text-200 flex-1">{sec.name}</span>
                <span className="text-text-500 flex-shrink-0">{sec.chart_names?.length ?? 0} charts</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modification input */}
      <div className="space-y-1.5">
        <label className="text-xs text-text-400 font-mono">Request changes</label>
        <div className="flex gap-2 items-end">
          <textarea
            className="flex-1 bg-bg-100 border border-border-300/20 focus:border-accent-main-100/50 rounded-md px-3 py-2 text-sm text-text-100 font-mono resize-none outline-none transition-colors placeholder:text-text-500 min-h-[2.5rem]"
            rows={2}
            value={instructions}
            onChange={e => setInstructions(e.target.value)}
            onKeyDown={handleKey}
            placeholder='e.g. "add a scatter plot of salary vs experience", "remove the pie chart", "rename section 2 to Regional Breakdown"'
            disabled={pending !== null}
          />
          <button
            onClick={() => send('modify')}
            disabled={pending !== null || !instructions.trim()}
            className="flex-shrink-0 px-3 py-2 bg-bg-200/60 hover:bg-bg-200 disabled:opacity-40 disabled:cursor-not-allowed border border-border-300/20 text-text-200 text-xs font-semibold font-mono rounded transition-colors h-10"
          >
            {pending === 'modify' ? (
              <span className="inline-block w-3.5 h-3.5 border-2 border-text-400 border-t-transparent rounded-full animate-spin" />
            ) : (
              <ArrowRight className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
        <p className="text-xs text-text-500 font-mono">Enter to apply · Shift+Enter for new line</p>
      </div>

      {/* Primary actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={() => send('regenerate')}
          disabled={pending !== null}
          className="px-4 py-1.5 bg-bg-200/60 hover:bg-bg-200 disabled:opacity-40 disabled:cursor-not-allowed border border-border-300/20 text-text-200 text-xs font-semibold font-mono rounded transition-colors"
        >
          {pending === 'regenerate' ? (
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 border-2 border-text-400 border-t-transparent rounded-full animate-spin" />
              Regenerating…
            </span>
          ) : 'Regenerate'}
        </button>
        <button
          onClick={() => send('accept')}
          disabled={pending !== null}
          className="flex-1 px-4 py-1.5 bg-accent-main-100 hover:bg-accent-main-100/90 disabled:opacity-40 disabled:cursor-not-allowed text-bg-000 text-xs font-semibold font-mono rounded transition-colors"
        >
          {pending === 'accept' ? (
            <span className="flex items-center justify-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 border-2 border-bg-000/60 border-t-transparent rounded-full animate-spin" />
              Starting…
            </span>
          ) : 'Run Analysis ↗'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update `PHASES` constant and component logic in `DeepAnalyzeBlock`**

Replace the `PHASES` const:

```tsx
const PHASES: { key: DeepAnalyzePhase; label: string }[] = [
  { key: 'enrich',    label: 'Enrich'    },
  { key: 'load',      label: 'Load'      },
  { key: 'profile',   label: 'Profile'   },
  { key: 'plan',      label: 'Plan'      },
  { key: 'extract',   label: 'Extract'   },
  { key: 'synthesize', label: 'Synthesize' },
  { key: 'report',    label: 'Report'    },
];
```

Add `'plan_reviewing'` to `STATUS_COLORS` and `STATUS_LABELS`:

```tsx
const STATUS_COLORS = {
  running:        'text-amber-400',
  plan_reviewing: 'text-purple-400',
  done:           'text-emerald-400',
  error:          'text-red-400',
  cancelled:      'text-text-400',
} as const;

const STATUS_LABELS = {
  running:        'Analyzing…',
  plan_reviewing: 'Awaiting plan review',
  done:           'Complete',
  error:          'Error',
  cancelled:      'Cancelled',
} as const;
```

- [ ] **Step 3: Update `DeepAnalyzeBlock` render — add plan review panel, remove insights/charts sections**

Update the destructuring in `DeepAnalyzeBlock`:

```tsx
export function DeepAnalyzeBlock({ message }: Props) {
  const {
    da_job_id,
    da_status = 'running',
    da_phases = {},
    da_load_rows,
    da_load_cols,
    da_plan_subtables,
    da_plan_charts,
    da_subtables = [],
    da_report_path,
    da_error,
    da_failed_phase,
  } = message;
```

Update `statusKey` to handle `plan_reviewing`:

```tsx
  const statusKey: keyof typeof STATUS_LABELS =
    da_status === 'cancelled'      ? 'cancelled' :
    da_status === 'error'          ? 'error' :
    da_status === 'done'           ? 'done' :
    da_status === 'plan_reviewing' ? 'plan_reviewing' : 'running';
```

Update the status stripe to show purple for `plan_reviewing`:

```tsx
      {/* Status stripe */}
      <div className={
        da_status === 'done'           ? 'h-0.5 bg-emerald-500/60' :
        da_status === 'error'          ? 'h-0.5 bg-red-500/60' :
        da_status === 'cancelled'      ? 'h-0.5 bg-text-500/40' :
        da_status === 'plan_reviewing' ? 'h-0.5 bg-purple-500/40' :
        'h-0.5 bg-bg-200'
      }>
        {da_status === 'running' && (
          <div
            className="h-full bg-accent-main-100 transition-all duration-500"
            style={{ width: `${Math.max((doneCount / PHASES.length) * 100, 3)}%` }}
          />
        )}
      </div>
```

After the phase pills section, add the plan review panel (conditionally):

```tsx
      {/* Plan review panel */}
      {da_status === 'plan_reviewing' && <PlanReviewPanel message={message} />}
```

Remove the entire **Charts** section (`{da_charts.length > 0 && ...}`) and the entire **Insights** section (`{da_insights.length > 0 && ...}`) from the render output. The sub-tables section remains.

Update the sub-tables section — remove `da_plan_charts` references:

```tsx
      {/* Sub-tables */}
      {da_subtables.length > 0 && (
        <div className="mx-4 mb-3 border border-border-300/10 rounded-md overflow-hidden">
          <div className="px-3 py-1.5 bg-bg-200/40 flex items-center justify-between">
            <span className="text-xs font-semibold text-text-200 font-mono">Sub-tables</span>
            <span className="text-xs text-text-500 font-mono">
              {da_subtables.filter(s => s.status === 'done').length}/{da_plan_subtables ?? da_subtables.length}
            </span>
          </div>
          <div className="divide-y divide-border-300/10">
            {da_subtables.map((s, i) => (
              <ItemRow
                key={i}
                name={s.name}
                status={s.status}
                error={s.error}
                suffix={s.status === 'done' ? `${s.rows.toLocaleString()} rows` : undefined}
              />
            ))}
          </div>
        </div>
      )}
```

Remove `openInsight` useState and `ReactMarkdown` import (no longer used).

- [ ] **Step 4: Build and verify**

```bash
cd web-ui && npm run build 2>&1 | tail -30
```

Expected: no TypeScript errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/components/Chat/DeepAnalyzeBlock.tsx
git commit -m "feat(frontend): DeepAnalyzeBlock plan review panel, remove insights/charts UI"
```

---

## Task 7: Build UI and final integration smoke test

- [ ] **Step 1: Build the web UI**

```bash
make build-ui
```

Expected: frontend built into `atria/web/static/`.

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest atria/skills/builtin/deep_analyze/tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit the built static assets**

```bash
git add atria/web/static/
git commit -m "chore: rebuild UI for deep_analyze v2"
```

---

## Self-Review Checklist

- [x] `depth` param flows: schema → job → engine → planner → prompt ✓
- [x] `modify_plan()` has fallback to original plan on failure ✓
- [x] Plan review loop uses `ctx.review_callback` — no-ops cleanly when `None` ✓
- [x] `uuid` import in pipeline uses local import to avoid circular issues ✓
- [x] `analyze.chart_data` emit is in a try/except — failure doesn't abort extraction ✓
- [x] `_fanout_render`, `_run_render`, `_fanout_insight` fully removed ✓
- [x] `_fanout_synthesize` simplified — no longer needs `chart_lookup` ✓
- [x] `_vision_insight` removed from `DeepAnalyzeEngine` ✓
- [x] Unified `request_review()` correctly dispatches by event type ✓
- [x] WS message type `analyze_plan_response` wired in `websocket.py` ✓
- [x] `da_status: 'plan_reviewing'` handled in store and component ✓
- [x] `analyze.chart` and `analyze.insight` WS handlers deleted from `chat.ts` ✓
- [x] `ReactMarkdown` and `openInsight` removed from `DeepAnalyzeBlock.tsx` ✓
