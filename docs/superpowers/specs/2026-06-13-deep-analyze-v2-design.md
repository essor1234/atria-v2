# deep_analyze v2 Design Spec

**Date:** 2026-06-13
**Status:** Approved

## Goal

Update the `deep_analyze` skill with three improvements:
1. A `depth` param (like `deep_research`) to control analysis scope
2. A plan review pause after planning — user can accept, modify, or regenerate before execution
3. Replace PNG chart rendering with data streaming to the UI via `analyze.chart_data` events (same payload shape as `send_data` tool), rendered client-side

## Pipeline: Before vs After

**Before:** `enrich → load → profile → plan → extract → render PNG → vision insight → synthesize → report`

**After:** `enrich → load → profile → plan → [pause: plan review] → extract + stream data → synthesize → report`

PNG rendering and vision insight phases are removed. Sub-table data is streamed to the UI after each extraction, and the UI renders charts client-side. Synthesis uses stats evidence only (already supported).

---

## 1. Depth Param

Add `depth: "fast" | "standard" | "deep"` to `PARAMS_DEEP_ANALYZE` (default `"standard"`). Mirrors `deep_research` schema exactly.

Passed to `run_planning()` → `build_planning_system()`. The planner prompt gets a scope instruction block:

- `fast`: 2 sections, 2–3 charts, 3 sub_tables
- `standard`: 3–4 sections, 4 charts, 4–5 sub_tables
- `deep`: 5 sections, 6 charts, 6 sub_tables

Add `depth: str` field to `AnalyzeJob`.

---

## 2. Plan Review Pause

### Backend

After `planner(profile)` returns in `run_job()`, enter a `while True` review loop:

```python
while True:
    request_id = uuid.uuid4().hex[:12]
    payload = {
        "type": "analyze.plan_ready",
        "job_id": job.job_id,
        "plan": job.plan,   # sections, charts, sub_tables
        "request_id": request_id,
    }
    result = ctx.review_callback(job.job_id, request_id, payload)
    action = result.get("action", "accept")
    if action == "modify":
        job.plan = modify_plan(job.plan, result["instructions"], chat_fn)
    elif action == "regenerate":
        job.plan = planner(job.profile_rich)
    else:
        break  # accept
job.sections = [dict(s) for s in job.plan.get("sections", [])]
```

If `ctx.review_callback` is None, skip the loop and proceed immediately (non-web path).

### `modify_plan(plan, instructions, chat_fn)` — new in `planning.py`

Mirrors `modify_taxonomy()` in deep_research. Sends the current plan JSON + user instructions to the LLM with a system prompt instructing it to apply the modifications and return updated valid plan JSON. Parses with the existing `_parse_plan()`. Falls back to the original plan on parse failure.

### Web wiring

**`web_ui_callback.py`**: Add `request_plan_review(job_id, request_id, event_payload)` method — identical structure to `request_taxonomy_review()`:
- Register pending state before broadcast (closes race condition)
- Broadcast the event
- Block on `threading.Event` with 10-minute timeout
- Return `{action, instructions}` on resolve

**`web/state.py`**: Add plan review pending state bucket (same pattern as taxonomy review: `add_pending_plan_review`, `get_pending_plan_review`, `clear_plan_review`).

**`SkillToolContext`**: The existing `review_callback` field is reused — the callback signature `(job_id, request_id, event_payload) -> result` is the same. The web session layer wires `request_plan_review` to `ctx.review_callback` when `deep_analyze` is running (same pattern as deep_research wires `request_taxonomy_review`).

> Note: `review_callback` is currently shared — if both `deep_research` and `deep_analyze` run concurrently in the same session, they both write to the same callback. This is acceptable since jobs have distinct `job_id` and `request_id` for disambiguation. No change needed.

---

## 3. Data Streaming (Replaces PNG)

### Pipeline change

In `_fanout_extract`, after each sub-table succeeds, immediately query its rows and emit `analyze.chart_data`:

```python
# after extractor succeeds and row count is confirmed:
chart_specs = [c for c in job.plan["charts"] if c["source_table"] == f"t_{spec['name']}"]
if chart_specs:
    rows_data = _query_table_rows(job.dir / "data.db", f"t_{spec['name']}")
    _emit(ctx, {
        "type": "analyze.chart_data",
        "job_id": job.job_id,
        "name": spec["name"],
        "columns": rows_data["columns"],   # [{name, type}]
        "rows": rows_data["rows"],          # [{col: value, ...}]
        "suggestions": [
            {"chart_type": c["type"], "x": c["x"], "y": c["y"], "title": c["title"]}
            for c in chart_specs
        ],
    })
```

`_query_table_rows(db_path, table_name)` is a new helper that:
- Connects to SQLite read-only
- Fetches all rows (capped at 10,000 rows, 50 columns — same limits as `send_data`)
- Infers column types using the same logic as `SendDataHandler._infer_column_type`
- Returns `{columns: [{name, type}], rows: [dict]}`

### Phases removed

- `_fanout_render` — removed from `run_job`
- `_fanout_insight` — removed from `run_job`
- Phase events `analyze.phase render` and `analyze.phase insight` — removed from pipeline emit calls

### Synthesis update

`_fanout_synthesize` already works without chart insights (the `chart_insights` param is an empty list and synthesis falls back to `stats_evidence` only). No change needed to synthesis logic.

### PDF report

The PDF report step is kept. It will no longer include chart images. This is acceptable — the interactive charts are shown in the UI during the session.

---

## 4. Frontend Changes

### New event types — `types/index.ts`

Add to the WS message type union:
- `'analyze.plan_ready'`
- `'analyze.chart_data'`

### `stores/chat.ts`

**`analyze.plan_ready`** handler (mirrors `deep_research_taxonomy_ready`):
- Sets `da_status: 'plan_reviewing'` on the deep_analyze message
- Stores `da_plan` (the plan object) and `da_plan_review_request_id`
- If message already exists for this `job_id`, update it; otherwise patch in-place

**`analyze.chart_data`** handler:
- Calls the same path as `data_message` / `send_data` result handling
- Appends a chart bubble to the session messages using the existing `ChartView` component
- Payload shape: `{title: spec.name, columns, rows, suggestions}`

### Plan review UI

Inside the deep_analyze message bubble, when `da_status === 'plan_reviewing'`:
- Show a summary of the plan: section names, chart count, sub-table count
- Text input for modification instructions
- Three buttons: **Accept**, **Modify**, **Regenerate**
- On submit, POST to the existing plan review resolve endpoint with `{action, instructions}`

The plan review resolve endpoint is a new route (mirrors the taxonomy review resolve route) that calls `state.resolve_plan_review(request_id, {action, instructions})` and signals the blocked worker thread.

### DA_PHASES update

Remove `render` and `insight` from the `DA_PHASES` constant (they no longer exist).

---

## Files Touched

### Backend
| File | Change |
|------|--------|
| `atria/skills/builtin/deep_analyze/schemas.py` | Add `depth` param |
| `atria/skills/builtin/deep_analyze/jobs.py` | Add `depth: str` field |
| `atria/skills/builtin/deep_analyze/prompts.py` | Add depth scope block to planner system prompt |
| `atria/skills/builtin/deep_analyze/planning.py` | Add `modify_plan()`, pass `depth` to `build_planning_system` |
| `atria/skills/builtin/deep_analyze/pipeline.py` | Add plan review loop, add `_query_table_rows`, emit `analyze.chart_data` after extract, remove render+insight fan-outs |
| `atria/skills/builtin/deep_analyze/engine.py` | Pass `depth` to job and planner |
| `atria/web/web_ui_callback.py` | Add `request_plan_review()` method |
| `atria/web/state.py` | Add plan review pending state bucket |
| `atria/web/routes/sessions.py` | Add plan review resolve route |

### Frontend
| File | Change |
|------|--------|
| `web-ui/src/types/index.ts` | Add `analyze.plan_ready`, `analyze.chart_data` to WS type union; add `da_plan`, `da_plan_review_request_id` to `Message` type; remove `render`/`insight` from DA_PHASES |
| `web-ui/src/stores/chat.ts` | Handle `analyze.plan_ready`, `analyze.chart_data`; remove `analyze.chart` PNG handler, remove `analyze.insight` handler; update DA_PHASES |
| `web-ui/src/components/Chat/DeepAnalyzeMessage.tsx` | Add plan review card (sections list + text input + Accept/Modify/Regenerate buttons) |

---

## Non-Goals

- Second pause after charts are shown (follow-up requests handled via normal chat after job completes)
- Keeping PNG charts in the PDF report
- Changing the synthesis or report generation logic
