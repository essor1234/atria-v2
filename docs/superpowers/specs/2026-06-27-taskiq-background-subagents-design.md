# TaskIQ Background Subagents — Design (Sub-project 1)

**Date:** 2026-06-27
**Status:** Approved design, pending implementation plan
**Scope:** Sub-project 1 of the DeLM port — the distributed task-queue *execution substrate*.

## Context

We are porting the architecture from the DeLM reference (`.references/DeLM/`) onto atria's
core agent. DeLM bundles two distinct capabilities:

1. **Parallel best-of-N solvers + a shared verified blackboard** — N agents work the same
   task concurrently, posting deterministically-verified typed notes to a shared blackboard
   that peers read, then results are aggregated best-of-N. This is DeLM's research
   contribution and improves answer quality/reliability.
2. **Durable distributed execution** — the substrate the solvers run on. DeLM runs its N
   solvers in-process via `asyncio.gather` + `asyncio.Semaphore`.

The full port is large (~3,600 lines in DeLM) and targets a *synchronous* atria agent loop
that does none of this today. We therefore decompose into two sequenced sub-projects, each
with its own spec → plan → build cycle:

- **Sub-project 1 (this spec):** TaskIQ execution substrate. Make background subagents real
  distributed tasks on TaskIQ workers + scheduler. No blackboard yet.
- **Sub-project 2 (later):** DeLM parallel-solver + shared verified blackboard, built on
  Sub-project 1.

Worker and scheduler use **TaskIQ** (explicit user preference).

### Decisions locked during brainstorming

- **Goal:** full DeLM port, sequenced; substrate first.
- **Task granularity:** background subagents only. Whole agent runs stay on the current
  in-thread `ThreadPoolExecutor`. This fills the existing `run_in_background` /
  `_get_subagent_output` stub and is the seam DeLM's N-way fan-out plugs into later.
- **Deployment target:** server mode primarily. Redis broker + result backend + a separate
  `taskiq worker` process. The local TUI keeps today's synchronous in-thread subagents
  (no change).
- **UI behavior:** fire-and-collect. The worker runs the subagent silently and returns a
  final result; no live streaming for the MVP. Real-time streaming can be added later via
  the existing `RedisBus`.
- **Implementation approach:** Approach 1 — TaskIQ task + payload-rebuild in worker + a
  sync-bridge client.

### Relevant existing code (integration points)

- `atria/core/agents/main_agent/run_loop.py:209` — `RunLoopMixin.run_sync(...)`, the
  synchronous (thread-based, no event loop) ReAct loop.
- `atria/core/agents/subagents/manager/execution.py:34` — `execute_subagent(...)`, currently
  synchronous and blocking; creates a fresh MainAgent with restricted tools.
- `atria/core/context_engineering/tools/registry.py:427` — `_execute_spawn_subagent(...)`;
  schema already exposes `run_in_background` (`task_tool.py:95`).
- `atria/core/context_engineering/tools/registry.py:624-666` — `_get_subagent_output(...)`,
  an **unimplemented stub** that returns an error and expects
  `manager.get_background_task_output(task_id, block, timeout)`.
- `atria/web/agent_executor.py:243-430` — `_run_agent_sync(...)` builds config, tools,
  RuntimeService, deps, and hooks fresh from a session. This construction logic is what the
  worker must reuse.
- `atria/web/bus.py:184` — `make_bus(kind, redis_url)` factory (`InMemoryBus` / `RedisBus`),
  the pattern our broker factory mirrors. `RedisBus` uses `psubscribe("atria:*")`.
- `atria/core/context_engineering/history/session_manager/pg_manager.py` — Postgres-backed
  session/message persistence (SQLAlchemy async + asyncpg).
- `pyproject.toml` — `redis>=5.0`, `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.29.0` already
  present. No queue/broker framework yet.

## Goals / Non-goals

**Goals**
- A background subagent runs as a durable TaskIQ task in a separate worker process.
- The synchronous main agent can enqueue a background subagent and later collect its result
  without blocking the turn.
- Establish worker **and** scheduler infrastructure (TaskIQ), ready for Sub-project 2's
  fan-out.
- No new infrastructure beyond the already-present Redis.

**Non-goals (this sub-project)**
- Shared blackboard, verifier, parallel best-of-N (Sub-project 2).
- Whole agent runs as tasks (web queries / `-p`).
- Live streaming of background subagent activity to the UI.
- Local-TUI background execution (kept synchronous).

## Architecture

One new package, `atria/core/tasks/`, plus a thin refactor that extracts dep/tool
construction into a shared builder. Three processes share Redis:

```
┌─ Server process (uvicorn) ────────────┐      ┌─ Worker process (taskiq worker) ─┐
│  Main agent run (sync, in thread)      │      │  asyncio event loop              │
│   └ spawn_subagent(run_in_background)  │      │   └ run_background_subagent task │
│        │                               │      │        └ rebuild deps from       │
│   TaskIQClient.enqueue() ──┐           │      │           payload → run_sync()   │
│                            ▼           │      │           (in a thread)          │
│                      ┌───────────────────────────────┐  │  returns result dict   │
│   get_background_..  │  Redis  broker + result backend│◄─┘                        │
│   TaskIQClient.await_result() ◄────────┘ (task queue + results)                  │
└────────────────────────────────────────┘      └──────────────────────────────────┘
        ▲                                                  scheduler process
        └─ janitor reaps stale tasks ──── TaskiqScheduler ─┘ (taskiq scheduler)
```

### The crux — bridging sync agent code to async TaskIQ

The agent loop is synchronous and runs in a thread with no event loop; TaskIQ's `.kiq()` and
`.wait_result()` are coroutines. `TaskIQClient` owns **one persistent background event loop on
a daemon thread**, started lazily, with the broker connected once. Synchronous callers use
`asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)` to enqueue and await. This
avoids per-call `asyncio.run()` (which would reconnect the broker every time) and keeps all
call sites synchronous — no signature changes ripple into the agent loop.

**Process roles:** the server enqueues and awaits only — it is *not* a worker
(`broker.is_worker_process` is False, so it runs `broker.startup()`/`shutdown()` in the
FastAPI lifespan). The worker runs as
`taskiq worker atria.core.tasks.broker:broker atria.core.tasks.tasks`. The scheduler runs as
`taskiq scheduler atria.core.tasks.scheduler:scheduler`. All three share Redis.

## Components

### `atria/core/tasks/broker.py`
`make_broker(redis_url) -> AsyncBroker` — a `ListQueueBroker` (taskiq-redis)
`.with_result_backend(RedisAsyncResultBackend(redis_url))`. Module-level `broker` singleton
for the worker/scheduler CLIs. Mirrors `make_bus` for consistent config/env handling. Result
TTL configurable (default 1h, sized ≥ max expected subagent runtime). Under `ENVIRONMENT=pytest`
the factory returns `InMemoryBroker(await_inplace=True)` so unit tests need no Redis.

### `atria/core/tasks/payload.py`
`SubagentTaskPayload` (Pydantic, fully JSON-serializable) — the contract that replaces shared
live objects across the process boundary:
- `session_id`, `owner_id` — reload the session and persist results.
- `subagent_type`, `prompt`, `description`.
- `working_dir`, `path_mapping`, `docker` flags.
- `config_snapshot` — resolved AppConfig the worker rebuilds from.
- `tool_names` / restrictions — the subagent's allowed tools.
- `parent_tool_call_id` — session-navigation (Ctrl+G) continuity.

A unit test asserts the payload round-trips through `model_dump_json`, so a future
non-serializable field fails CI rather than production.

### `atria/core/agents/deps_builder.py` (refactor, not new behavior)
Extract the dep/tool/RuntimeService assembly currently inlined in
`agent_executor._run_agent_sync` (≈ lines 243–430) into
`build_runtime_and_deps(payload) -> (RuntimeService, AgentDependencies)`. **Both** the web
executor and the worker call this single builder, so they cannot drift. This is the only
meaningful change to existing code. A test guards equivalence with the prior inline build.

### `atria/core/tasks/tasks.py`
```python
@broker.task
async def run_background_subagent(payload: dict) -> dict:
    p = SubagentTaskPayload.model_validate(payload)
    runtime, deps = build_runtime_and_deps(p)
    # run_sync is blocking → keep the worker loop responsive
    result = await asyncio.to_thread(_run_subagent_sync, runtime, deps, p)
    return result  # {success, content, messages, completion_status}
```
Fire-and-collect: no bus broadcasts in the MVP.

### `atria/core/tasks/client.py`
`TaskIQClient` — the sync bridge:
- `enqueue(payload) -> task_id`
- `await_result(task_id, block, timeout) -> dict`
- `is_ready(task_id) -> bool`

Reconstructs the task handle from `task_id` + result backend, so the awaiting server process
needs no in-memory handle. Owns the persistent background loop described in the crux.

### `atria/core/tasks/scheduler.py`
`TaskiqScheduler(broker, [LabelScheduleSource(broker)])` plus one janitor:
`@broker.task(schedule=[{"cron": "*/10 * * * *"}])` that reaps expired/orphaned task
bookkeeping. Establishes the scheduler process for Sub-project 2.

### Wiring into existing code (surgical)
- `SubagentManager.execute_subagent` (`subagents/manager/execution.py:34`): when
  `run_in_background=True`, build payload → `client.enqueue()` → return
  `{task_id, status: "running"}` instead of running inline.
- `registry.py:624-666` `_get_subagent_output()`: replace the stub with
  `client.await_result(task_id, block, timeout)`.
- `registry.py` `_execute_spawn_subagent`: pass `run_in_background` through to the manager
  (schema already has it).
- Server lifespan (`server.py:80`): `broker.startup()`/`shutdown()` guarded by
  `if not broker.is_worker_process`.
- `pyproject.toml`: add `taskiq`, `taskiq-redis`.

## Data flow (end-to-end lifecycle)

**Enqueue**
1. LLM emits `spawn_subagent(subagent_type=…, prompt=…, run_in_background=true)`.
2. `registry._execute_spawn_subagent` → `manager.execute_subagent(run_in_background=True)`.
3. Manager builds `SubagentTaskPayload` from the live `deps` + session context (it serializes
   the *inputs*, not the objects).
4. `TaskIQClient.enqueue(payload)` → `run_background_subagent.kiq(payload.model_dump())` over
   the background loop → Redis. Returns `task_id`.
5. Tool result to the LLM: `{task_id, status: "running"}`. The main agent loop continues —
   non-blocking.

**Execute (worker)**
6. Worker pops the task, calls `build_runtime_and_deps(payload)` — reloads the session via
   `pg_manager.load_session(session_id, owner_id)`, rebuilds config/tools/MCP/RuntimeService
   fresh.
7. Runs `run_sync(prompt, deps, …)` inside `asyncio.to_thread`. Fire-and-collect: no bus
   broadcasts.
8. Returns `{success, content, messages, completion_status}` → Redis result backend (TTL).

**Collect**
9. A later turn: the LLM calls `get_subagent_output(task_id)` (or it is auto-collected at a
   join point).
10. `registry._get_subagent_output` → `client.await_result(task_id, block, timeout)`.
11. Result rendered back to the LLM with the existing `_llm_suffix` formatting;
    `parent_tool_call_id` preserved for Ctrl+G navigation.

**Persistence boundary:** the worker reloads the session read-mostly to build context, but the
**main agent thread owns session writes** — the collected result is appended to the parent
session as a normal tool result. The worker does *not* write to the parent conversation,
avoiding concurrent-mutation (sessions are already locked during runs at
`agent_executor.py:356`). Worker-side subagent messages live only in the returned `messages`
payload.

## Error handling & edge cases

- **Worker exception** → task fails; `await_result` maps it to
  `{success: false, error, status: "failed"}` so the LLM sees a clean failure, never a stack
  trace. Matches today's stub error shape.
- **Timeout on collect** → `wait_result(timeout)` expires → return `{status: "running"}` so
  the LLM can poll again or move on. `block=false` does a non-blocking `is_ready` check.
- **Redis unavailable at enqueue** → `enqueue` raises; the manager falls back to running the
  subagent **inline** (today's synchronous behavior) and logs a warning. Background execution
  degrades gracefully rather than hard-failing the user's turn.
- **Worker crash / lost task** → result never lands; the janitor flags tasks past a max-age as
  `orphaned`; `await_result` past deadline returns `failed` with reason `orphaned`. For the
  MVP we default to **at-most-once** (no auto-redelivery) and surface the loss, rather than
  risk double-execution of side-effecting tools. Acks/visibility-timeout for at-least-once is
  a deliberate later toggle.
- **Result expiry (TTL)** → collecting after TTL returns `{status: "expired"}`.
- **Payload can't rebuild** (session deleted, working_dir gone) → worker returns `failed`
  early with the reason; no partial work.
- **Serialization guard** → `SubagentTaskPayload` is the only thing crossing the boundary; a
  unit test asserts round-trip so a non-serializable field fails CI.

## Testing

Per project rules: unit tests **and** a real end-to-end run with `OPENAI_API_KEY`.

**Unit (`InMemoryBroker`, no Redis)**
- Broker swaps to `InMemoryBroker(await_inplace=True)` under `ENVIRONMENT=pytest`.
- `SubagentTaskPayload` JSON round-trip; rejects a non-serializable field.
- `TaskIQClient.enqueue`/`await_result` happy path; timeout → `running`; failed task →
  `failed`.
- `build_runtime_and_deps(payload)` produces deps equivalent to `_run_agent_sync`'s inline
  build (guards the refactor).
- Manager: `run_in_background=True` enqueues and returns `task_id`; Redis-down falls back to
  inline.
- `registry._get_subagent_output` returns formatted output (replaces the stubbed error path);
  update existing tests that assert the stub.
- Janitor marks an over-age task `orphaned`.

**End-to-end (real, server mode)**
- Redis up; `taskiq worker …` running; issue a web/`-p` query that triggers
  `spawn_subagent(run_in_background=true)`.
- Confirm the main turn returns immediately with a `task_id`, the worker executes against a
  real LLM, and a follow-up `get_subagent_output` returns the real result.
- Verify a forced worker kill surfaces `orphaned`, not a hang.

## Open items / forward hooks for Sub-project 2

- The `run_background_subagent` task + `SubagentTaskPayload` generalize to "run solver N of M"
  by adding `thread_id` / `n_threads` and a `shared_lessons_ref`.
- The fire-and-collect collect path becomes the best-of-N aggregation join point.
- The bus-streaming option (deferred here) is where solver progress would surface.
