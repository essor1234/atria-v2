# Divide-Work Multi-Agent Orchestration — Design Spec

> Sub-project 2, Phase 2c. Sibling of `parallel/` (competitive solvers + judge).
> This phase adds **collaborative work-division**: one request is split into a
> task DAG and worked by multiple background agents that share one module.

## Goal

A user chats on a single **module** (e.g. `item_flow_tracking`). The system
decomposes the request into a DAG of subtasks (task 1/2/3…, with mixed
dependencies), dispatches each subtask to a **background worker agent**, and the
workers collaborate over a **shared context** (the module's data + a shared
verified blackboard). Results are gathered into a summary returned to the user.
A `/divide` page tracks progress live.

This is **collaborative** (each worker does a *distinct* piece), not
**competitive** — there is no judge, no winner, no diff-apply. It is contrasted
with `solve_parallel` (Phase 2b), which runs N solvers on the *same* task and
picks the best.

## Decisions (locked with the user, 2026-06-27)

1. **Work type:** *operational* — workers use the module's existing
   commands/skills (read + write) to fulfil the request. No code editing of the
   module.
2. **Task dependencies:** *mixed* — most subtasks independent (run in parallel),
   some depend on others → a small DAG, not a flat fan-out.
3. **Decomposition:** the coordinator decomposes automatically via an LLM call
   (reads the user request + the module's `SKILL.md`).
4. **Autonomy / writes:** **fully autonomous, uniform** — *everything* is
   dispatched to background workers (including the coordinator), and **all
   actions auto-approve, including writes**. There is **no approval step** and no
   foreground coordinator. (This supersedes an earlier "writes need approval"
   decision; the user changed their mind to a uniform all-dispatch model. It
   aligns with the standing project rule that background subagents always run
   auto-approve because they have no UI.)
5. **Shared context = the module:** workers share (a) the module's on-disk data
   (one SQLite DB) and (b) a per-job verified blackboard.

## Architecture

New self-contained package **`atria/core/divide/`**, structured as a sibling of
`atria/core/parallel/` and reusing its patterns (job store, TaskIQ fan-out, WS
events, tracking page).

```
User chat (on a module)
  │
  main agent calls tool  divide_work(request, module)
  │   → enqueue ONE coordinator task (background)          ← coordinator is itself dispatched
  ▼
Coordinator task (background, no UI, autonomous):
  1. decompose: LLM(request + module SKILL.md) → DAG tasks {id, description, depends_on[]}
  2. job_store.save(job)                                   ← Redis key atria:dw:{job_id}
  3. schedule loop:
       ready = tasks whose depends_on are all done
       enqueue ready as module-worker tasks (≤ max_parallel) via task client
       await any worker → store result → unlock dependents → repeat
  4. write summary into the job
  ▼
Workers (background, autonomous, auto-approve ALL incl. writes):
  • subagent = the module's gateway subagent (atria/core/modules/subagent.py)
  • toolset: bash (module scripts) + module SKILL.md injected + NOTE
  • shared BLACKBOARD (blackboard_task_id = "dw_{job_id}")
  • shared module SQLite (WAL + busy_timeout → serialized writes)
  ▲──────────────── shared context ────────────────┘
  │
main agent polls  get_divide_result(job_id)  → status + per-task + summary
Frontend /divide page → live DAG/progress via WebSocket
```

### Why coordinator-as-background-task works

TaskIQ workers are **async**: when the coordinator `await`s a sub-worker result
it yields the event loop rather than hard-blocking the process, so the same
worker pool can run the sub-workers concurrently.

**Deployment constraint (must document + guard):** because a background
coordinator awaits background workers (nested dispatch), worker concurrency must
be **≥ 2** (recommended ≥ `max_parallel` + 1) — the coordinator holds one async
slot; the workers need the rest. The coordinator carries a total **timeout** and
a **no-progress detector** that aborts the job with a clear "increase worker
concurrency" error rather than hanging.

## Components (each one responsibility)

1. **`decompose.py`** — `decompose(request, module_skill, llm_call, max_tasks) ->
   list[DivideTask]`. One LLM call returns JSON `[{id, description,
   depends_on}]`. Pure aside from the injected `llm_call`. Validates: acyclic,
   ids unique and referenced-only, count ≤ `max_tasks`. One retry on JSON-parse
   failure; then raise a typed error the coordinator turns into job `failed`.
2. **`job_store.py`** — Redis CRUD for one job at `atria:dw:{job_id}` (mirrors
   `parallel/job_store.py`): `save/load/delete`, TTL = `pjob_ttl`.
3. **`scheduler.py`** — the DAG schedule loop. Pure-ish: takes injectable
   `enqueue(task)->task_id` and `await_result(task_id)->dict` callables so it is
   unit-testable without Redis/TaskIQ. Implements ready-set selection,
   `max_parallel` cap, result capture, dependent unlocking, and skip-on-parent-
   failure.
4. **coordinator task** — `run_divide_coordinator(payload)` registered on the
   TaskIQ broker. Wires `decompose` + `scheduler` with a real task client +
   `job_store`, emits progress events, writes the final summary.
5. **worker** — *reuses* the module's gateway subagent (`module-worker`) and the
   existing `SubagentTaskPayload` (already carries `blackboard_task_id`,
   `thread_id`, `prompt`, `working_dir`, `subagent_type`). No new payload.
6. **`tools.py`** — `divide_work` + `get_divide_result` handlers + a
   `build_divide_orchestrator(...)` helper (mirrors `parallel/tools.py`).
7. **frontend** — `/divide` page + nav link + `divideJobs` Zustand store (mirrors
   the `/parallel` page just shipped).

## Data model (Redis `atria:dw:{job_id}`)

```python
DivideTask = {
    "id": str,                 # "t1"
    "description": str,        # what the worker should do
    "depends_on": list[str],   # task ids
    "status": str,             # pending | ready | running | done | failed | skipped
    "result": str | None,      # worker's summary output
    "task_id": str | None,     # TaskIQ task id once enqueued
}
DivideJob = {
    "job_id": str,
    "module": str,                       # "item_flow_tracking"
    "request": str,                      # original user chat
    "blackboard_task_id": str,           # "dw_{job_id}"
    "tasks": list[DivideTask],
    "status": str,                       # decomposing | running | done | failed
    "summary": str | None,
}
```

`DivideConfig` (on `AppConfig.divide`): `max_tasks` (default 8), `max_parallel`
(default 3), `pjob_ttl` (default 3600), `redis_url`, `job_timeout_s` (coordinator
total timeout).

## Data flow & context sharing

- **Down to dependent tasks:** a worker's prompt includes (a) the **shared
  blackboard digest** (every worker's verified NOTEs so far) and (b) the
  **summaries of its parent tasks** inlined directly. Two layers: broad shared
  board + direct parent results.
- **Up from workers:** each worker writes NOTEs (FACT/OBSERVED/…) to the shared
  blackboard and returns a result-summary string captured into its `DivideTask`.

## Failure handling / graceful degradation

The blackboard is an *accelerant*; nothing here may raise into the agent loop.

- No task client / worker / Redis → `divide_work` returns a soft error ("needs
  worker + Redis"), never crashes (mirrors `solve_parallel`).
- Decompose LLM failure / invalid JSON → one retry, then job `failed` + reason.
- Cyclic / invalid DAG → rejected at decompose, job `failed` + reason.
- Worker dies/fails → that task `failed`; its dependents `skipped`; the job still
  ends `done` with a failed/skipped list (independent tasks finish).
- Blackboard down → workers still run; `NOTE` soft-fails (Phase 2a degradation);
  only the sharing is lost.
- SQLite contention → WAL + `busy_timeout` retry; on persistent lock the worker's
  task fails (caught) and is reported.
- Nested-dispatch stall → coordinator `job_timeout_s` + no-progress detector
  aborts with a clear error; job has a TTL for cleanup.
- Every tool path returns a soft error dict; never raises (mirrors
  `parallel/tools.py`).

## Tools & wiring

- `divide_work(request, module)` → enqueue coordinator → `{job_id,
  status:"running"}`.
- `get_divide_result(job_id, block, timeout)` → job status + per-task statuses +
  summary.
- `registry.py`: `_get_divide_orchestrator(ui_callback=…)` (lazy, needs task
  client; binds `progress_cb` to `ui_callback.on_divide_event` when present), and
  two additive dispatch handlers. Both pass `getattr(context, "ui_callback",
  None)`. All additive (default-safe when the feature/worker is absent).

## Frontend `/divide`

Mirrors the `/parallel` page shipped in Phase 2b's UI work.

- Nav link "Divide" + route `/divide` (AuthGuard) + `divideJobs` Zustand store
  self-registering WS handlers once.
- WS events (coordinator → `progress_cb` → `WebUICallback.on_divide_event` →
  broadcast; protocol constants added additively):
  - `divide_job_started` → `{job_id, module, request, tasks:[{id, description,
    depends_on}], session_id}`
  - `divide_task_update` → `{job_id, task_id, status, result?, session_id}`
  - `divide_job_done` → `{job_id, status, summary, session_id}`
- Page renders the task list as a DAG (status badges pending/running/done/
  failed/skipped, dependencies shown), with the final summary. Matches
  `web-ui/DESIGN.md` tokens; clones the `/parallel` card idioms.

## Testing

Unit, dependency-injected, no live Redis/LLM/worker:
- `decompose.py` — JSON parse + DAG validation (acyclic, id integrity, max_tasks)
  with a stubbed `llm_call`.
- `scheduler.py` — schedule order under mixed dependencies; skip propagation when
  a parent fails; `max_parallel` respected — using fake `enqueue`/`await_result`.
- `job_store.py` — `fakeredis` roundtrip.
- `tools.py` — `divide_work` returns a `job_id`; returns a soft error when no
  task client.
- Frontend — `pnpm build`/`tsc` clean; store reducers cover started/task_update/
  done.

**Deferred to the user (no infra in sandbox):** live multi-process e2e (Redis +
TaskIQ worker(s) with concurrency ≥ 2 + live LLM). Runbook: set the worker
concurrency, start Redis + worker(s), enable the module, chat a decomposable
request, watch `/divide` populate and the module data change.

## Reuse map

| Need | Reused from |
|---|---|
| Background dispatch + await | TaskIQ client/broker (Sub-project 1) |
| Shared verified context | blackboard (Phase 2a), `blackboard_task_id="dw_{job}"` |
| Worker subagent | module gateway subagent (`atria/core/modules/subagent.py`) |
| Worker payload | existing `SubagentTaskPayload` (no new payload) |
| Job store / fan-out / WS / tracking page | `atria/core/parallel/*` + `/parallel` UI patterns |

## Out of scope (this phase)

- No approval step, no judge, no winner selection, no git-worktree isolation
  (workers share the real module data on purpose).
- TUI surface (web only, matching the `/parallel` decision).
- Cross-module jobs (one job targets one module).
- Durable archival of jobs beyond the Redis TTL.
- Live multi-process e2e (deferred to the user's environment).
