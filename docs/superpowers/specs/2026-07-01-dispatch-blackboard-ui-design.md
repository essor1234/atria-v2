# Dispatch Rewire + Blackboard UI Stream — Design

Date: 2026-07-01
Status: Approved via brainstorming, awaiting user spec review.

## Goal

1. Rewire the existing `spawn_subagent` tool so the main agent can delegate work through the DeLM dispatch backends (`core/divide/` DAG decomposition and `core/parallel/` worktree solvers) without changing the tool name or breaking existing prompts.
2. Stream blackboard notes to the Dispatch page in real time so users can watch task/thread reasoning as it happens.

Non-goals:
- Removing or deprecating `spawn_subagent`.
- Redesigning `core/divide/`, `core/parallel/`, or `core/blackboard/` internals.
- Building a global cross-job blackboard browser.

## Context

Current state:
- `atria/core/agents/subagents/task_tool.py` defines `spawn_subagent` — routes to `SubAgentManager` per `subagent_type` (10 types: solver, planner, code_explorer, ask_user, pr_reviewer, security_reviewer, project_init, module_worker, web_clone, web_generator).
- `atria/core/divide/orchestrator.py` and `atria/core/parallel/orchestrator.py` implement DAG decomposition and racing worktree solvers. Both already stamp `blackboard_task_id = "bb_" + job_id` and use `core/blackboard/store.py` (Redis-backed).
- Dispatch page (`web-ui/src/pages/DispatchPage.tsx`) renders divide + parallel jobs from `stores/solverJobs.ts`. No blackboard notes surfaced today.
- Blackboard notes are only read by the parallel judge (`ParallelOrchestrator._read_notes`) and archived to Postgres at job end.

## Design

### §1 Tool rewire

`spawn_subagent` schema gains one optional field:

```
strategy: "direct" | "divide" | "parallel"   (default "direct")
```

Handler in `atria/core/context_engineering/tools/registry_mixins/subagent_ops.py` branches on strategy:

- `direct` — existing path (`SubAgentManager.execute`). Zero behavior change. `subagent_type` required.
- `divide` — call `DivideOrchestrator.run(request=prompt, module=subagent_type_hint)`. `subagent_type` becomes an optional module hint.
- `parallel` — call `ParallelOrchestrator.run(task=prompt, n=cfg.parallel_default_n)`. `subagent_type` becomes an optional solver-role hint.

Result shape for dispatch strategies:
```
{"success": bool, "content": "<final summary>", "job_id": "<uuid>"}
```
`job_id` lets the agent poll via existing `get_subagent_output` (extended to recognize dispatch job ids by prefix / registry lookup).

Prompt update in `templates/system/main/`: short section "When to use which strategy" — divide for decomposable multi-step, parallel for single task worth racing solvers, direct for quick focused delegation.

Fallback: if strategy=divide or parallel and redis/docker unavailable, handler returns an error result telling the agent to retry with `strategy="direct"`.

### §2 Blackboard → UI stream

**Publisher** (`atria/core/blackboard/store.py`):
- After each successful `BlackboardStore.append`, publish JSON `{task_id, thread_id, type, content, ts}` to Redis channel `atria:bb:{task_id}:notes`.
- Wrapped in try/except; publish failure never breaks the append (best-effort accelerant).

**Web subscriber** (`atria/web/blackboard_subscriber.py`, new):
- Single background asyncio task started on web server boot.
- Uses a single Redis psub on pattern `atria:bb:*:notes` (avoids per-task connection churn).
- Parses task_id from channel name, looks up matching dispatch `job_id` (from a small `bb_id → job_id` map maintained when a job is registered).
- Broadcasts to the existing WS as `{event: "blackboard.note", job_id, thread_id, note: {type, content, ts}}`.
- Server-side throttle: >10 notes/s per task_id drops middle notes (keeps first + last), logs a warning.

Job registration already emits `{event: "dispatch.job_register", job_id, blackboard_task_id, ...}` via existing dispatch tools — the subscriber uses this event to update its map. On `dispatch.job_done`, entry removed.

### §3 Frontend store + UI

**Store extension** (`web-ui/src/stores/solverJobs.ts`):
```
type BBNote = { type: string; content: string; ts: number; thread_id: number }
DivideTaskView += { notes: BBNote[] }
ThreadState   += { notes: BBNote[] }
```
- WS handler for `blackboard.note`: find job by `job_id`; push into matching task (divide: task id `t{thread_id}`) or thread (parallel: `thread === thread_id`).
- Cap 50 notes per task/thread — drop oldest on overflow.

**Render** (`DispatchPage.tsx`):
- `TaskRow` and `ThreadRow` gain a collapsible notes block below existing content.
- Default collapsed when >3 notes; show last 3 inline with a "… N more" toggle.
- Each note: one line `[type-badge] content` truncate w/ full-content tooltip.
- Type → color:
  - fact → slate
  - question → amber
  - decision → emerald
  - blocker → semantic-danger
  - other → text-400
- Latest note appended: brief 200ms bg-fade highlight (accessibility: respect `prefers-reduced-motion`).
- Zero notes + status=pending → notes block hidden entirely.

### §4 Testing + rollout

Unit tests:
- `tests/test_subagent_dispatch.py`
  - strategy=direct → `SubAgentManager.execute` called; existing result shape returned.
  - strategy=divide → `DivideOrchestrator.run` called with `request=prompt`; result includes `job_id`.
  - strategy=parallel → `ParallelOrchestrator.run` called; result includes `job_id`.
  - redis/docker unavailable + dispatch strategy → returns error with fallback hint.
- `tests/test_blackboard_pubsub.py`
  - `BlackboardStore.append` publishes correct JSON to `atria:bb:{task_id}:notes`.
  - Publisher failure (redis down) does not break append; return path unchanged.
- `tests/test_blackboard_subscriber.py`
  - psub message → WS broadcast shape `{event, job_id, thread_id, note}`.
  - Throttle: >10 msg/s for one task → middle dropped, first + last kept, warning logged.

E2E (per project CLAUDE.md, uses `OPENAI_API_KEY`):
- `atria run ui` + prompt: "spawn 3 parallel solvers to fix X" → observe DispatchPage rendering the job with notes streaming under each thread.
- `atria -p "…"` with strategy=divide → job completes, blackboard notes archived to Postgres (verify via db query).

Rollout phases:
1. Schema + handler branches + unit tests.
2. Blackboard pub/sub publisher + web subscriber + WS event.
3. Store field + UI notes render.
4. Prompt update teaching the LLM when to pick divide/parallel.

Each phase is independently mergeable and reversible.

## Risks

- Redis pubsub connection leak → subscriber uses a single psub, closed on web shutdown.
- Note flood → server throttle + client 50-cap.
- Dispatch strategies require redis + docker; when unavailable the handler returns a structured error so the agent can retry with `strategy="direct"`.
- `subagent_type` semantics change (hint vs required) — mitigated by keeping it required for `direct` (current behavior).

## Files touched

New:
- `atria/web/blackboard_subscriber.py`
- `tests/test_subagent_dispatch.py`
- `tests/test_blackboard_pubsub.py`
- `tests/test_blackboard_subscriber.py`

Modified:
- `atria/core/agents/subagents/task_tool.py` (add strategy field to schema)
- `atria/core/context_engineering/tools/registry_mixins/subagent_ops.py` (dispatch branches)
- `atria/core/blackboard/store.py` (publish on append)
- `atria/web/server.py` or startup module (register subscriber)
- `atria/web/websocket.py` (blackboard.note event shape)
- `atria/core/agents/prompts/templates/system/main/*.md` (strategy guidance section)
- `web-ui/src/stores/solverJobs.ts` (BBNote type + WS handler + notes fields)
- `web-ui/src/pages/DispatchPage.tsx` (TaskRow + ThreadRow notes block)
