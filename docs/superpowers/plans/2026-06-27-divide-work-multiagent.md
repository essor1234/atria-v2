# Divide-Work Multi-Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose a user request on one module into a task DAG, dispatch each subtask to a background worker agent that shares the module's data + a verified blackboard, and gather results into a summary — tracked live on a `/divide` page.

**Architecture:** A self-contained `atria/core/divide/` package mirroring `atria/core/parallel/`: pure `decompose` (LLM→DAG) + `scheduler` (dependency-aware loop), a Redis `job_store`, a background `run_divide_coordinator` TaskIQ task, and two tools (`divide_work`/`get_divide_result`). Workers reuse a new static `module_worker` subagent + the existing `SubagentTaskPayload` + the blackboard. Everything is dispatched (uniform), fully autonomous (no approval).

**Tech Stack:** Python 3.11+, `redis.asyncio`, `fakeredis` (dev), `taskiq` (already present), Pydantic v2, pytest + pytest-asyncio; web-ui React/Vite/Zustand/Tailwind.

## Global Constraints

- Line length 100 (Black + Ruff). Type hints on public APIs (mypy strict). Google-style docstrings.
- No new runtime deps (taskiq, redis.asyncio, SQLAlchemy already present; `fakeredis` already a dev dep).
- Redis key prefix for jobs: `atria:dw:`. Blackboard id per job: `dw_{job_id}`. Default `DivideConfig`: `max_tasks=8`, `max_parallel=3`, `pjob_ttl=3600`, `job_timeout_s=600`, `redis_url="redis://localhost:6379/0"`.
- Task statuses EXACTLY: `pending | ready | running | done | failed | skipped`. Job statuses EXACTLY: `decomposing | running | done | failed`.
- The blackboard/divide system is an ACCELERANT: any Redis/worker/LLM failure degrades gracefully (soft tool error / job `failed` with reason); never raises into the agent run.
- Workers are background TaskIQ subagents, fully autonomous (auto-approve all actions incl. writes). No approval step.
- Coordinator awaits workers asynchronously; nested dispatch requires worker concurrency ≥ 2 (document + guard with `job_timeout_s` + no-progress detection).
- Run tests with `.venv/bin/pytest` (NOT `uv run pytest`); set `ENVIRONMENT=pytest`. Per project preference, implementers run ONLY their own new test file per task; the full suite is batched to the final task.
- `docs/` is gitignored → use `git add -f` for any docs file.
- Conventional Commit messages; NO `Co-Authored-By: Claude` trailer (hard project rule).
- Mirror `atria/core/parallel/*` conventions exactly where a sibling exists (job_store, tools, WS wiring). Mirror the shipped `/parallel` web-ui files for `/divide`.

---

### Task 1: DivideConfig + job models + Redis job store

**Files:**
- Create: `atria/core/divide/__init__.py`
- Create: `atria/core/divide/models.py`
- Create: `atria/core/divide/job_store.py`
- Modify: `atria/models/config.py` (add `DivideConfig`, attach to `AppConfig`)
- Test: `tests/core/divide/test_job_store.py` (+ `tests/core/divide/__init__.py`)

**Interfaces:**
- Produces: `DivideTask`/`DivideJob` Pydantic models with `to_dict`/`from_dict` via `model_dump`/`model_validate`; `DivideConfig(max_tasks, max_parallel, pjob_ttl, job_timeout_s, redis_url)`; `AppConfig.divide`; `JobStore(redis)` with async `save(job_id, record, ttl)`, `load(job_id)->dict|None`, `delete(job_id)`. Key prefix `atria:dw:`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/divide/test_job_store.py
import pytest

from atria.core.divide.job_store import JobStore


@pytest.mark.asyncio
async def test_save_load_delete_roundtrip():
    from fakeredis import aioredis as fake_aioredis

    r = fake_aioredis.FakeRedis()
    store = JobStore(r)
    rec = {"job_id": "j1", "module": "item_flow_tracking", "tasks": [], "status": "running"}
    await store.save("j1", rec, ttl=60)
    assert await store.load("j1") == rec
    await store.delete("j1")
    assert await store.load("j1") is None


@pytest.mark.asyncio
async def test_load_missing_is_none():
    from fakeredis import aioredis as fake_aioredis

    assert await JobStore(fake_aioredis.FakeRedis()).load("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_job_store.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement models, config, job store**

```python
# atria/core/divide/__init__.py
"""Collaborative work-division multi-agent orchestration (DeLM Phase 2c)."""
```

```python
# atria/core/divide/models.py
"""Task-DAG + job models for divide-work orchestration."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DivideTask(BaseModel):
    """One node in the work-division DAG."""

    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending|ready|running|done|failed|skipped
    result: str | None = None
    task_id: str | None = None  # TaskIQ task id once enqueued


class DivideJob(BaseModel):
    """A whole divide-work job: the request, its DAG, and the rollup."""

    job_id: str
    module: str
    request: str
    blackboard_task_id: str
    tasks: list[DivideTask] = Field(default_factory=list)
    status: str = "decomposing"  # decomposing|running|done|failed
    summary: str | None = None
```

```python
# atria/core/divide/job_store.py
"""Redis-backed record for an in-flight divide-work job. Caller owns the redis client."""
from __future__ import annotations

import json

_PREFIX = "atria:dw:"


class JobStore:
    """CRUD for divide-work job records keyed atria:dw:{job_id}."""

    def __init__(self, redis: object) -> None:
        self._redis = redis

    async def save(self, job_id: str, record: dict, ttl: int) -> None:
        await self._redis.set(_PREFIX + job_id, json.dumps(record), ex=ttl)  # type: ignore[attr-defined]

    async def load(self, job_id: str) -> dict | None:
        raw = await self._redis.get(_PREFIX + job_id)  # type: ignore[attr-defined]
        if raw is None:
            return None
        s = raw.decode() if isinstance(raw, bytes) else raw
        return json.loads(s)

    async def delete(self, job_id: str) -> None:
        await self._redis.delete(_PREFIX + job_id)  # type: ignore[attr-defined]
```

In `atria/models/config.py`, below `ParallelConfig` (around line 133-160), add:

```python
class DivideConfig(BaseModel):
    """Work-division multi-agent (DeLM Phase 2c) settings."""

    max_tasks: int = 8          # cap on decomposed subtasks
    max_parallel: int = 3       # max workers running at once
    pjob_ttl: int = 3600        # seconds a divide job lives in Redis
    job_timeout_s: int = 600    # coordinator total/no-progress timeout
    redis_url: str = "redis://localhost:6379/0"
```

And in `AppConfig`, alongside `parallel` (around line 233):

```python
    divide: DivideConfig = Field(default_factory=DivideConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_job_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/divide/__init__.py atria/core/divide/models.py atria/core/divide/job_store.py atria/models/config.py tests/core/divide/
git commit -m "feat(divide): job models + config + redis job store"
```

---

### Task 2: Decompose (LLM → task DAG) + validation

**Files:**
- Create: `atria/core/divide/decompose.py`
- Test: `tests/core/divide/test_decompose.py`

**Interfaces:**
- Consumes: `DivideTask` (Task 1).
- Produces: `decompose(request: str, module_skill: str, llm_call: Callable[[str, str], str], max_tasks: int) -> list[DivideTask]`. Parses a JSON array `[{id, description, depends_on}]` from the LLM, validates (unique ids, deps reference existing ids, acyclic, count ≤ max_tasks), one retry on JSON-parse failure, then raises `DecomposeError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/divide/test_decompose.py
import pytest

from atria.core.divide.decompose import DecomposeError, decompose


def _llm(payload):
    # llm_call(system, user) -> assistant text; return a canned JSON DAG
    def _call(system, user):
        return payload
    return _call


def test_parses_valid_dag():
    body = '[{"id":"t1","description":"count","depends_on":[]},'\
           ' {"id":"t2","description":"report","depends_on":["t1"]}]'
    tasks = decompose("req", "skill", _llm(body), max_tasks=8)
    assert [t.id for t in tasks] == ["t1", "t2"]
    assert tasks[1].depends_on == ["t1"]


def test_rejects_cycle():
    body = '[{"id":"a","description":"x","depends_on":["b"]},'\
           ' {"id":"b","description":"y","depends_on":["a"]}]'
    with pytest.raises(DecomposeError):
        decompose("req", "skill", _llm(body), max_tasks=8)


def test_rejects_unknown_dependency():
    body = '[{"id":"a","description":"x","depends_on":["ghost"]}]'
    with pytest.raises(DecomposeError):
        decompose("req", "skill", _llm(body), max_tasks=8)


def test_enforces_max_tasks():
    body = "[" + ",".join(
        f'{{"id":"t{i}","description":"d","depends_on":[]}}' for i in range(20)
    ) + "]"
    with pytest.raises(DecomposeError):
        decompose("req", "skill", _llm(body), max_tasks=8)


def test_retries_then_raises_on_bad_json():
    calls = {"n": 0}

    def _bad(system, user):
        calls["n"] += 1
        return "not json"

    with pytest.raises(DecomposeError):
        decompose("req", "skill", _bad, max_tasks=8)
    assert calls["n"] == 2  # one retry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_decompose.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement decompose**

```python
# atria/core/divide/decompose.py
"""Turn a user request into a validated task DAG via one LLM call. No raising into callers above DecomposeError."""
from __future__ import annotations

import json
import re
from typing import Callable

from atria.core.divide.models import DivideTask

_SYSTEM = (
    "You split a user's request about ONE module into a small DAG of subtasks for "
    "parallel worker agents. Output ONLY a JSON array, no prose. Each element: "
    '{"id": "t1", "description": "<one concrete subtask>", "depends_on": ["<ids>"]}. '
    "Keep tasks independent where possible; use depends_on only for true ordering. "
    "Use the module's documented commands. Max tasks as instructed."
)


class DecomposeError(Exception):
    """Raised when the LLM output cannot be turned into a valid task DAG."""


def _extract_json_array(text: str) -> list:
    text = text.strip()
    # Tolerate code fences around the array.
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON array found")
    return json.loads(m.group(0))


def _validate(raw: list, max_tasks: int) -> list[DivideTask]:
    if not isinstance(raw, list) or not raw:
        raise DecomposeError("empty or non-list DAG")
    if len(raw) > max_tasks:
        raise DecomposeError(f"too many tasks: {len(raw)} > {max_tasks}")
    tasks = [DivideTask(id=str(d["id"]), description=str(d["description"]),
                        depends_on=[str(x) for x in d.get("depends_on", [])]) for d in raw]
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise DecomposeError("duplicate task ids")
    idset = set(ids)
    for t in tasks:
        for dep in t.depends_on:
            if dep not in idset:
                raise DecomposeError(f"task {t.id} depends on unknown {dep}")
    # Cycle check via DFS.
    graph = {t.id: t.depends_on for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}

    def visit(node: str) -> None:
        color[node] = GRAY
        for dep in graph[node]:
            if color[dep] == GRAY:
                raise DecomposeError("dependency cycle detected")
            if color[dep] == WHITE:
                visit(dep)
        color[node] = BLACK

    for i in ids:
        if color[i] == WHITE:
            visit(i)
    return tasks


def decompose(
    request: str,
    module_skill: str,
    llm_call: Callable[[str, str], str],
    max_tasks: int,
) -> list[DivideTask]:
    """Ask the LLM for a task DAG; validate it. Retry once on parse failure."""
    user = f"Module skill:\n{module_skill}\n\nUser request:\n{request}\n\nMax tasks: {max_tasks}"
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            raw = _extract_json_array(llm_call(_SYSTEM, user))
            return _validate(raw, max_tasks)
        except DecomposeError:
            raise
        except Exception as exc:  # noqa: BLE001 — parse/format errors retry once
            last_exc = exc
    raise DecomposeError(f"could not parse DAG: {last_exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_decompose.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/divide/decompose.py tests/core/divide/test_decompose.py
git commit -m "feat(divide): LLM decompose request into validated task DAG"
```

---

### Task 3: Scheduler (dependency-aware loop, skip-on-fail)

**Files:**
- Create: `atria/core/divide/scheduler.py`
- Test: `tests/core/divide/test_scheduler.py`

**Interfaces:**
- Consumes: `DivideTask` (Task 1).
- Produces: `async schedule(tasks: list[DivideTask], enqueue: Callable[[DivideTask], Awaitable[str]], await_one: Callable[[list[str]], Awaitable[tuple[str, dict]]], max_parallel: int, on_change: Callable[[DivideTask], Awaitable[None]] | None = None) -> list[DivideTask]`. Runs the DAG: enqueues ready tasks (≤ max_parallel in flight), awaits whichever finishes, stores `result`/`status`, marks `done`/`failed`, propagates `skipped` to dependents of failed tasks, calls `on_change` per status transition. Returns the finished task list. Never raises (a worker error → that task `failed`).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/divide/test_scheduler.py
import asyncio

import pytest

from atria.core.divide.models import DivideTask
from atria.core.divide.scheduler import schedule


def _tasks():
    return [
        DivideTask(id="a", description="A", depends_on=[]),
        DivideTask(id="b", description="B", depends_on=[]),
        DivideTask(id="c", description="C", depends_on=["a", "b"]),
    ]


@pytest.mark.asyncio
async def test_runs_dag_in_dependency_order():
    started: list[str] = []

    async def enqueue(t):
        started.append(t.id)
        return f"tid-{t.id}"

    async def await_one(inflight):
        tid = inflight[0]
        return tid, {"status": "done", "output": f"ok-{tid}"}

    out = await schedule(_tasks(), enqueue, await_one, max_parallel=3)
    by = {t.id: t for t in out}
    assert all(by[i].status == "done" for i in ["a", "b", "c"])
    # c only enqueues after a and b finished
    assert started.index("c") > started.index("a")
    assert started.index("c") > started.index("b")


@pytest.mark.asyncio
async def test_parent_failure_skips_dependents():
    async def enqueue(t):
        return f"tid-{t.id}"

    async def await_one(inflight):
        tid = inflight[0]
        status = "failed" if tid == "tid-a" else "done"
        return tid, {"status": status, "error": "boom" if status == "failed" else None}

    out = await schedule(_tasks(), enqueue, await_one, max_parallel=3)
    by = {t.id: t for t in out}
    assert by["a"].status == "failed"
    assert by["c"].status == "skipped"   # depends on failed a
    assert by["b"].status == "done"      # independent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_scheduler.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement scheduler**

```python
# atria/core/divide/scheduler.py
"""Dependency-aware schedule loop for a divide-work DAG. Worker-agnostic via injected callables."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from atria.core.divide.models import DivideTask

logger = logging.getLogger(__name__)

EnqueueFn = Callable[[DivideTask], Awaitable[str]]
AwaitOneFn = Callable[[list[str]], Awaitable[tuple[str, dict]]]
OnChangeFn = Callable[[DivideTask], Awaitable[None]]


async def _notify(on_change: OnChangeFn | None, task: DivideTask) -> None:
    if on_change is None:
        return
    try:
        await on_change(task)
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks scheduling
        logger.warning("divide on_change failed: %s", exc)


async def schedule(
    tasks: list[DivideTask],
    enqueue: EnqueueFn,
    await_one: AwaitOneFn,
    max_parallel: int,
    on_change: OnChangeFn | None = None,
) -> list[DivideTask]:
    """Run the DAG: enqueue ready tasks (≤ max_parallel), await, unlock, skip-on-fail."""
    by_id = {t.id: t for t in tasks}
    inflight: dict[str, DivideTask] = {}  # task_id -> task

    def _deps_done(t: DivideTask) -> bool:
        return all(by_id[d].status == "done" for d in t.depends_on)

    def _dep_failed(t: DivideTask) -> bool:
        return any(by_id[d].status in ("failed", "skipped") for d in t.depends_on)

    while True:
        # Mark tasks whose deps failed as skipped.
        for t in tasks:
            if t.status == "pending" and _dep_failed(t):
                t.status = "skipped"
                await _notify(on_change, t)
        # Enqueue ready tasks up to the parallel cap.
        for t in tasks:
            if len(inflight) >= max_parallel:
                break
            if t.status == "pending" and _deps_done(t):
                t.status = "running"
                await _notify(on_change, t)
                tid = await enqueue(t)
                t.task_id = tid
                inflight[tid] = t
        if not inflight:
            # Nothing running: done when no pending remain.
            if not any(t.status == "pending" for t in tasks):
                break
            continue  # only blocked-by-skip remain; loop marks them skipped
        tid, result = await await_one(list(inflight.keys()))
        t = inflight.pop(tid, None)
        if t is None:
            continue
        if result.get("status") == "done":
            t.status = "done"
            t.result = str(result.get("output") or result.get("summary") or "")
        else:
            t.status = "failed"
            t.result = str(result.get("error") or "worker failed")
        await _notify(on_change, t)
    return tasks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_scheduler.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/divide/scheduler.py tests/core/divide/test_scheduler.py
git commit -m "feat(divide): dependency-aware DAG scheduler with skip-on-fail"
```

---

### Task 4: `module_worker` static subagent spec

**Files:**
- Create: `atria/core/agents/subagents/agents/module_worker.py`
- Modify: `atria/core/agents/subagents/agents/__init__.py` (register `MODULE_WORKER_SUBAGENT`)
- Test: `tests/core/divide/test_module_worker_spec.py`

**Interfaces:**
- Consumes: the `SubAgentSpec` shape + `load_prompt` (mirror `solver.py`).
- Produces: `MODULE_WORKER_SUBAGENT: SubAgentSpec` named `"module_worker"`, tools = `["run_command", "invoke_skill", "read_file", "write_file"]` (matches `DEFAULT_MODULE_SUBAGENT_TOOLS`). The coordinator (Task 5) injects the per-module gateway block + subtask + parent results into `payload.prompt`; this spec is the generic, always-registered worker so the headless worker resolves `subagent_type="module_worker"` without dynamic module-subagent registration.

- [ ] **Step 1: Inspect the reference spec**

Run: `cat atria/core/agents/subagents/agents/solver.py` and `sed -n '1,20p' atria/core/agents/subagents/agents/__init__.py`
Mirror `SOLVER_SUBAGENT`'s structure exactly (same keys, same registration style).

- [ ] **Step 2: Write the failing test**

```python
# tests/core/divide/test_module_worker_spec.py
def test_module_worker_spec_shape():
    from atria.core.agents.subagents.agents import MODULE_WORKER_SUBAGENT

    assert MODULE_WORKER_SUBAGENT["name"] == "module_worker"
    assert "run_command" in MODULE_WORKER_SUBAGENT["tools"]
    assert MODULE_WORKER_SUBAGENT["system_prompt"]  # non-empty base prompt
```

- [ ] **Step 3: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_module_worker_spec.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 4: Implement the spec + register it**

```python
# atria/core/agents/subagents/agents/module_worker.py
"""Module-worker subagent: one autonomous worker in a divide-work job (DeLM Phase 2c).

Generic and always-registered so background workers resolve subagent_type
"module_worker" headlessly. The per-module gateway block + the concrete subtask
+ upstream results are injected by the coordinator into the run prompt.
"""
from __future__ import annotations

from atria.core.agents.prompts.loader import load_prompt
from atria.core.agents.subagents.specs import SubAgentSpec

_FALLBACK = (
    "You are one worker in a collaborative multi-agent job operating a single "
    "module. Do ONLY your assigned subtask using the module's documented "
    "commands (run scripts with absolute paths; invoke_skill before guessing "
    "flags). Other workers share a blackboard — write short verified NOTEs about "
    "what you find/do so peers can build on it, and return a concise result "
    "summary. Your module context and subtask follow."
)

MODULE_WORKER_SUBAGENT: SubAgentSpec = {
    "name": "module_worker",
    "description": (
        "Autonomous worker for one subtask of a divide-work job on a module. "
        "Shares a blackboard with peer workers; returns a result summary."
    ),
    "system_prompt": load_prompt("subagents/subagent-module-worker", fallback=_FALLBACK),
    "tools": ["run_command", "invoke_skill", "read_file", "write_file"],
}
```

In `atria/core/agents/subagents/agents/__init__.py`, mirror the `solver` import/export:

```python
from .module_worker import MODULE_WORKER_SUBAGENT
```

and add `MODULE_WORKER_SUBAGENT` to whatever aggregate list/registration the file exposes (follow the exact pattern used for `SOLVER_SUBAGENT` in that file — e.g. append it to the `ALL_SUBAGENTS`/registry list there).

- [ ] **Step 5: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_module_worker_spec.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add atria/core/agents/subagents/agents/module_worker.py atria/core/agents/subagents/agents/__init__.py tests/core/divide/test_module_worker_spec.py
git commit -m "feat(divide): module_worker static subagent spec"
```

---

### Task 5: Coordinator orchestrator (decompose + schedule + worker enqueue)

**Files:**
- Create: `atria/core/divide/orchestrator.py`
- Test: `tests/core/divide/test_orchestrator.py`

**Interfaces:**
- Consumes: `decompose` (T2), `schedule` (T3), `JobStore` (T1), `DivideJob`/`DivideTask` (T1), `MODULE_WORKER_SUBAGENT` name (T4), `build_module_gateway_block` (`atria/core/modules/subagent.py`), `SubagentTaskPayload` (`atria/core/tasks/payload.py`).
- Produces: `DivideOrchestrator(job_store, redis_client, llm_call, config, run_async, enqueue_worker, await_worker, modules_root, owner_id, session_id, progress_cb=None)` with `start(request, module, module_skill) -> str` (decompose, persist job, run schedule loop, write summary; returns job_id) and `collect(job_id, block, timeout_ms) -> dict` (load + shape current job state). `enqueue_worker(payload)->Awaitable[str]` and `await_worker(task_ids)->Awaitable[tuple[str,dict]]` are injected so the loop is testable without TaskIQ. Emits `progress_cb(stage, data)` at `started`/`task_update`/`done`. Never raises (job→failed with reason).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/divide/test_orchestrator.py
import asyncio

import pytest

from atria.core.divide.orchestrator import DivideOrchestrator


class _Cfg:
    max_tasks = 8
    max_parallel = 3
    pjob_ttl = 60
    job_timeout_s = 30
    redis_url = "redis://x"


def _llm(system, user):
    return '[{"id":"t1","description":"count items","depends_on":[]},'\
           ' {"id":"t2","description":"report","depends_on":["t1"]}]'


@pytest.mark.asyncio
async def test_start_runs_dag_and_emits_events(monkeypatch):
    from fakeredis import aioredis as fake_aioredis
    from atria.core.divide.job_store import JobStore

    monkeypatch.setattr(
        "atria.core.divide.orchestrator.build_module_gateway_block",
        lambda m, root: "GATEWAY",
    )

    events: list = []
    loop = asyncio.get_running_loop()

    async def enqueue_worker(payload):
        return f"tid-{payload.thread_id}"

    async def await_worker(tids):
        return tids[0], {"status": "done", "output": "ok"}

    def run_async(coro):
        return loop.run_until_complete(coro) if not loop.is_running() else None

    orch = DivideOrchestrator(
        job_store=JobStore(fake_aioredis.FakeRedis()),
        redis_client=fake_aioredis.FakeRedis(),
        llm_call=_llm,
        config=_Cfg(),
        run_async=lambda c: c,  # unused in async path below
        enqueue_worker=enqueue_worker,
        await_worker=await_worker,
        modules_root="/modules",
        owner_id="u1",
        session_id="s1",
        progress_cb=lambda stage, data: events.append((stage, data)),
    )
    job_id = await orch.start_async("count then report", module=object(), module_skill="SKILL")
    state = await orch.collect_async(job_id)
    assert state["status"] == "done"
    assert {t["id"] for t in state["tasks"]} == {"t1", "t2"}
    assert any(e[0] == "started" for e in events)
    assert any(e[0] == "done" for e in events)
```

> Note: expose async `start_async`/`collect_async` as the testable core; the sync
> `start`/`collect` wrap them via `run_async`. The injected `enqueue_worker`/
> `await_worker` keep the test free of TaskIQ.

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_orchestrator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the orchestrator**

```python
# atria/core/divide/orchestrator.py
"""Divide-work coordinator: decompose → schedule → gather. Worker I/O is injected."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable

from atria.core.divide.decompose import DecomposeError, decompose
from atria.core.divide.job_store import JobStore
from atria.core.divide.models import DivideJob, DivideTask
from atria.core.divide.scheduler import schedule
from atria.core.modules.subagent import build_module_gateway_block
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


class DivideOrchestrator:
    """Run one divide-work job. Enqueue/await callables decouple it from TaskIQ."""

    def __init__(
        self,
        job_store: JobStore,
        redis_client: Any,
        llm_call: Callable[[str, str], str],
        config: Any,
        run_async: Callable[[Any], Any],
        enqueue_worker: Callable[[SubagentTaskPayload], Awaitable[str]],
        await_worker: Callable[[list[str]], Awaitable[tuple[str, dict]]],
        modules_root: str,
        owner_id: str,
        session_id: str,
        progress_cb: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._js = job_store
        self._redis = redis_client
        self._llm = llm_call
        self._cfg = config
        self._run_async = run_async
        self._enqueue = enqueue_worker
        self._await = await_worker
        self._root = modules_root
        self._owner = owner_id
        self._session = session_id
        self._cb = progress_cb

    def _emit(self, stage: str, data: dict) -> None:
        if self._cb is None:
            return
        try:
            self._cb(stage, data)
        except Exception as exc:  # noqa: BLE001 — telemetry never breaks the job
            logger.warning("divide progress_cb failed at %s: %s", stage, exc)

    def start(self, request: str, module: Any, module_skill: str) -> str:
        return self._run_async(self.start_async(request, module, module_skill))

    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        return self._run_async(self.collect_async(job_id))

    async def start_async(self, request: str, module: Any, module_skill: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        module_name = getattr(module, "name", str(module))
        bb_id = "dw_" + job_id
        job = DivideJob(job_id=job_id, module=module_name, request=request,
                        blackboard_task_id=bb_id, status="decomposing")
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        try:
            tasks = decompose(request, module_skill, self._llm, self._cfg.max_tasks)
        except DecomposeError as exc:
            job.status = "failed"
            job.summary = f"decompose failed: {exc}"
            await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
            self._emit("done", {"job_id": job_id, "status": "failed", "summary": job.summary})
            return job_id

        job.tasks = tasks
        job.status = "running"
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        self._emit("started", {
            "job_id": job_id, "module": module_name, "request": request,
            "tasks": [{"id": t.id, "description": t.description, "depends_on": t.depends_on}
                      for t in tasks],
        })

        gateway = build_module_gateway_block(module, self._root) if not isinstance(module, str) \
            else module_skill
        by_id = {t.id: t for t in tasks}

        async def enqueue(t: DivideTask) -> str:
            parents = "\n".join(f"- {by_id[d].id}: {by_id[d].result or ''}" for d in t.depends_on)
            prompt = (
                f"{gateway}\n\n## Your subtask\n{t.description}\n\n"
                + (f"## Upstream results\n{parents}\n" if parents else "")
            )
            payload = SubagentTaskPayload(
                session_id=self._session, owner_id=self._owner,
                subagent_type="module_worker", prompt=prompt,
                working_dir=self._root, config_snapshot={},
                blackboard_task_id=bb_id, thread_id=int(t.id.lstrip("t") or 0)
                if t.id.lstrip("t").isdigit() else 0,
            )
            return await self._enqueue(payload)

        async def on_change(t: DivideTask) -> None:
            await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
            self._emit("task_update", {"job_id": job_id, "task_id": t.id,
                                       "status": t.status, "result": t.result})

        await schedule(tasks, enqueue, self._await, self._cfg.max_parallel, on_change)

        n_done = sum(1 for t in tasks if t.status == "done")
        n_fail = sum(1 for t in tasks if t.status in ("failed", "skipped"))
        job.status = "done"
        job.summary = f"{n_done}/{len(tasks)} tasks done, {n_fail} failed/skipped."
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        self._emit("done", {"job_id": job_id, "status": "done", "summary": job.summary})
        return job_id

    async def collect_async(self, job_id: str) -> dict:
        rec = await self._js.load(job_id)
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}
        return rec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/core/divide/orchestrator.py tests/core/divide/test_orchestrator.py
git commit -m "feat(divide): coordinator orchestrator (decompose+schedule+gather)"
```

---

### Task 6: Coordinator TaskIQ task + tools + registry wiring

**Files:**
- Create: `atria/core/divide/tasks.py` (the `run_divide_coordinator` TaskIQ task)
- Create: `atria/core/divide/tools.py` (`build_divide_orchestrator`, `execute_divide_work`, `execute_get_divide_result`)
- Modify: `atria/core/context_engineering/tools/registry.py` (lazy `_get_divide_orchestrator(ui_callback=…)`, dispatch `divide_work`/`get_divide_result`)
- Modify: `atria/core/agents/components/schemas/definitions.py` (register `divide_work` + `get_divide_result` tool schemas)
- Test: `tests/core/divide/test_tools.py`

**Interfaces:**
- Consumes: `DivideOrchestrator` (T5), `JobStore` (T1), the TaskIQ broker singleton + `SubagentTaskPayload` (worker enqueue/await built from the broker like `TaskIQClient._enqueue_async`/`_await_async`), `build_orchestrator` patterns from `atria/core/parallel/tools.py`.
- Produces: `execute_divide_work(arguments, orchestrator, module, module_skill) -> dict` returning `{success, job_id, status, output}`; `execute_get_divide_result(arguments, orchestrator) -> dict`. Registry handlers `_execute_divide_work`/`_execute_get_divide_result` mirror `_execute_solve_parallel`/`_execute_get_parallel_result` exactly (same None-guard, same `ui_callback` passthrough).

- [ ] **Step 1: Inspect the parallel reference**

Run: `cat atria/core/parallel/tools.py` and `sed -n '700,775p' atria/core/context_engineering/tools/registry.py`
Mirror `build_orchestrator` + `_get_parallel_orchestrator` + the two dispatch handlers exactly. The coordinator-as-background-task differs: `divide_work` enqueues `run_divide_coordinator` (a TaskIQ task) rather than running the schedule loop inline.

- [ ] **Step 2: Write the failing test**

```python
# tests/core/divide/test_tools.py
from atria.core.divide.tools import execute_divide_work, execute_get_divide_result


class _Orch:
    def __init__(self):
        self.started = None

    def start(self, request, module, module_skill):
        self.started = (request, module, module_skill)
        return "job123"

    def collect(self, job_id, block=True, timeout_ms=30000):
        return {"job_id": job_id, "status": "running"}


def test_divide_work_returns_job_id():
    orch = _Orch()
    out = execute_divide_work({"request": "do X"}, orch, module="item_flow_tracking",
                              module_skill="SKILL")
    assert out["success"] is True
    assert out["job_id"] == "job123"


def test_divide_work_requires_request():
    out = execute_divide_work({}, _Orch(), module="m", module_skill="s")
    assert out["success"] is False


def test_get_divide_result_passthrough():
    out = execute_get_divide_result({"job_id": "job123"}, _Orch())
    assert out["output"]["status"] == "running"


def test_get_divide_result_requires_job_id():
    out = execute_get_divide_result({}, _Orch())
    assert out["success"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_tools.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement tasks.py + tools.py**

```python
# atria/core/divide/tools.py
"""Tool handlers + orchestrator builder for divide_work / get_divide_result.

Mirrors atria/core/parallel/tools.py. divide_work enqueues a background
coordinator task (run_divide_coordinator); get_divide_result reads job state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from atria.core.divide.job_store import JobStore
from atria.core.divide.orchestrator import DivideOrchestrator
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


def build_divide_orchestrator(
    task_client: Any,
    config: Any,
    llm_call: Callable[[str, str], str],
    modules_root: str,
    owner_id: str,
    session_id: str,
    progress_cb: Callable[[str, dict], None] | None = None,
    redis_client: Any = None,
) -> DivideOrchestrator:
    """Construct a DivideOrchestrator that fans workers out over the task client's broker."""
    divide_cfg = getattr(config, "divide", None) or config
    task_client.startup()

    def run_async(coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, task_client._loop).result()

    if redis_client is None:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(getattr(divide_cfg, "redis_url", "redis://localhost:6379/0"))

    broker = task_client._broker

    async def enqueue_worker(payload: SubagentTaskPayload) -> str:
        from atria.core.tasks.client import _TASK_NAME
        from atria.core.tasks import meta

        task = broker.find_task(_TASK_NAME)
        if task is None:
            raise RuntimeError(f"task {_TASK_NAME} not registered")
        kicked = await task.kiq(payload.model_dump())
        await meta.record_enqueue(redis_client, kicked.task_id, payload.session_id)
        return kicked.task_id

    async def await_worker(task_ids: list[str]) -> tuple[str, dict]:
        backend = broker.result_backend
        while True:
            for tid in task_ids:
                if await backend.is_result_ready(tid):
                    res = await backend.get_result(tid, with_logs=False)
                    if res.is_err:
                        return tid, {"status": "failed", "error": str(res.error)}
                    val = res.return_value or {}
                    return tid, {**val, "status": "done"}
            await asyncio.sleep(0.25)

    return DivideOrchestrator(
        job_store=JobStore(redis_client), redis_client=redis_client, llm_call=llm_call,
        config=divide_cfg, run_async=run_async, enqueue_worker=enqueue_worker,
        await_worker=await_worker, modules_root=modules_root, owner_id=owner_id,
        session_id=session_id, progress_cb=progress_cb,
    )


def execute_divide_work(arguments: dict, orchestrator: DivideOrchestrator, module: Any,
                        module_skill: str) -> dict:
    """Decompose + dispatch a divide-work job. Returns {job_id, status}."""
    request = arguments.get("request") or arguments.get("task") or ""
    if not request:
        return {"success": False, "error": "request is required", "output": None}
    try:
        job_id = orchestrator.start(request, module, module_skill)
    except Exception as exc:  # noqa: BLE001 — surface as tool error, never crash the loop
        logger.warning("divide_work start failed: %s", exc)
        return {"success": False, "error": f"divide_work failed: {exc}", "output": None}
    return {"success": True, "job_id": job_id, "status": "running",
            "output": f"[DIVIDE STARTED] job_id={job_id}. Use get_divide_result(job_id)."}


def execute_get_divide_result(arguments: dict, orchestrator: DivideOrchestrator) -> dict:
    """Return current job state (tasks + summary)."""
    job_id = arguments.get("job_id", "")
    if not job_id:
        return {"success": False, "error": "job_id is required", "output": None}
    try:
        result = orchestrator.collect(job_id, block=arguments.get("block", True),
                                      timeout_ms=arguments.get("timeout", 30000))
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_divide_result failed: %s", exc)
        return {"success": False, "error": f"get_divide_result failed: {exc}", "output": None}
    return {"success": result.get("status") != "unknown", "output": result}
```

> **`run_divide_coordinator` decision:** the simplest correct realization is to run
> the schedule loop inside `orchestrator.start` driven by the task client (the
> orchestrator already does this via injected `enqueue_worker`/`await_worker`).
> Because `divide_work` is called from the agent's tool path (which already owns a
> `TaskIQClient` whose loop runs workers), the loop runs on that client's loop —
> no separate coordinator task is strictly required for correctness, and it avoids
> the nested-worker-slot concern entirely. If a fully detached coordinator is
> desired later, wrap `start_async` in a registered TaskIQ task `run_divide_coordinator`
> and have `divide_work` `kiq` it; the orchestrator code is unchanged. For THIS
> plan, implement the task-client-driven loop (no separate coordinator task file)
> and DELETE the `atria/core/divide/tasks.py` create-step — note this in the commit.

In `registry.py`, mirror `_get_parallel_orchestrator` / `_execute_solve_parallel` / `_execute_get_parallel_result` (around lines 715-773): add `_get_divide_orchestrator(self, ui_callback=None)` (lazy build via `build_divide_orchestrator` using `self._subagent_manager._task_client`, `self._app_config`, `self.skill_ctx.llm_chat`, the modules root, owner/session from `context.session_manager.current_session`, and `progress_cb = ui_callback.on_divide_event if ui_callback and hasattr(...) else None`), plus `_execute_divide_work`/`_execute_get_divide_result` handlers added to the dispatch map at lines ~282-283. The `module` + `module_skill` come from the active module context (resolve via the module registry; if unavailable, return a soft error "no active module").

In `definitions.py`, register `divide_work` (required string `request`, optional string `module`) and `get_divide_result` (required string `job_id`, optional `block`/`timeout`) tool schemas — mirror the `solve_parallel`/`get_parallel_result` schemas exactly.

- [ ] **Step 5: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_tools.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add atria/core/divide/tools.py atria/core/context_engineering/tools/registry.py atria/core/agents/components/schemas/definitions.py tests/core/divide/test_tools.py
git commit -m "feat(divide): divide_work/get_divide_result tools + registry wiring"
```

---

### Task 7: WebSocket events (backend)

**Files:**
- Modify: `atria/web/protocol.py` (add `DIVIDE_*` message-type constants)
- Modify: `atria/web/web_ui_callback.py` (add `on_divide_event(stage, data)`)
- Test: `tests/core/divide/test_ws_events.py`

**Interfaces:**
- Consumes: the `progress_cb(stage, data)` contract from the orchestrator (T5) — stages `started`/`task_update`/`done`.
- Produces: protocol constants `DIVIDE_JOB_STARTED="divide_job_started"`, `DIVIDE_TASK_UPDATE="divide_task_update"`, `DIVIDE_JOB_DONE="divide_job_done"`; `WebUICallback.on_divide_event(stage, data)` maps stage→type, adds `session_id`, calls `self._broadcast`. (This is the same shape as the `on_parallel_solver_event` already shipped — mirror it.)

- [ ] **Step 1: Write the failing test**

```python
# tests/core/divide/test_ws_events.py
def test_on_divide_event_maps_and_broadcasts():
    from atria.web.web_ui_callback import WebUICallback

    sent = []

    cb = WebUICallback.__new__(WebUICallback)   # bypass __init__
    cb.session_id = "s1"
    cb._broadcast = lambda msg: sent.append(msg)

    cb.on_divide_event("started", {"job_id": "j1", "module": "m", "request": "r", "tasks": []})
    cb.on_divide_event("task_update", {"job_id": "j1", "task_id": "t1", "status": "done"})
    cb.on_divide_event("done", {"job_id": "j1", "status": "done", "summary": "ok"})
    cb.on_divide_event("bogus", {"x": 1})  # ignored

    types = [m["type"] for m in sent]
    assert types == ["divide_job_started", "divide_task_update", "divide_job_done"]
    assert all(m["data"]["session_id"] == "s1" for m in sent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_ws_events.py -v`
Expected: FAIL — AttributeError / missing constants.

- [ ] **Step 3: Implement protocol constants + callback**

In `atria/web/protocol.py`, next to the `PARALLEL_SOLVER_*` constants add (match the existing class/style):

```python
    DIVIDE_JOB_STARTED = "divide_job_started"
    DIVIDE_TASK_UPDATE = "divide_task_update"
    DIVIDE_JOB_DONE = "divide_job_done"
```

In `atria/web/web_ui_callback.py`, next to `on_parallel_solver_event` add:

```python
    def on_divide_event(self, stage: str, data: dict) -> None:
        """Broadcast a divide-work coordinator event (started/task_update/done)."""
        mapping = {
            "started": WSMessageType.DIVIDE_JOB_STARTED,
            "task_update": WSMessageType.DIVIDE_TASK_UPDATE,
            "done": WSMessageType.DIVIDE_JOB_DONE,
        }
        msg_type = mapping.get(stage)
        if msg_type is None:
            return
        self._broadcast({"type": msg_type, "data": {**data, "session_id": self.session_id}})
```

(Use the exact `WSMessageType` symbol already imported in that file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/test_ws_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/web/protocol.py atria/web/web_ui_callback.py tests/core/divide/test_ws_events.py
git commit -m "feat(divide): websocket events for divide-work jobs"
```

---

### Task 8: Frontend `/divide` page

**Files:**
- Modify: `web-ui/src/types/index.ts` (add 3 event-type literals to the WS union)
- Create: `web-ui/src/stores/divideJobs.ts`
- Create: `web-ui/src/pages/DivideAgentsPage.tsx`
- Modify: `web-ui/src/App.tsx` (route `/divide`)
- Modify: `web-ui/src/components/Layout/AppNavBar.tsx` (nav link "Divide")
- Test: build/typecheck (no unit test runner for the page; reducer logic kept pure)

**Interfaces:**
- Consumes: WS events `divide_job_started {job_id, module, request, tasks:[{id,description,depends_on}], session_id}`, `divide_task_update {job_id, task_id, status, result?, session_id}`, `divide_job_done {job_id, status, summary, session_id}`.
- Produces: a `divideJobs` Zustand store `{jobs: Record<jobId, DivideJobView>; order: string[]; clear()}` and a `/divide` page. **Mirror the shipped `/parallel` files exactly** — `web-ui/src/stores/parallelJobs.ts`, `web-ui/src/pages/ParallelAgentsPage.tsx`, and the `/parallel` route + nav link added to `App.tsx`/`AppNavBar.tsx`.

- [ ] **Step 1: Study the shipped /parallel pattern**

Run: `cat web-ui/src/stores/parallelJobs.ts web-ui/src/pages/ParallelAgentsPage.tsx` and `grep -n "parallel\|Parallel" web-ui/src/App.tsx web-ui/src/components/Layout/AppNavBar.tsx`
The `/divide` page is the structural twin: same card idiom, status badges, empty state, nav/route wiring, and the self-registering-once WS store pattern. Replace the data model with the DAG shape below.

- [ ] **Step 2: Add WS event literals**

In `web-ui/src/types/index.ts` add `'divide_job_started' | 'divide_task_update' | 'divide_job_done'` to the WS message-type union (next to the `parallel_solver_*` literals).

- [ ] **Step 3: Implement the store** (`web-ui/src/stores/divideJobs.ts`)

Mirror `parallelJobs.ts`. State per job:

```ts
type DivideTaskView = { id: string; description: string; depends_on: string[];
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'; result?: string };
type DivideJobView = { jobId: string; module: string; request: string;
  tasks: DivideTaskView[]; status: 'running' | 'done' | 'failed';
  summary?: string; startedAt: number; updatedAt: number };
```

- On `divide_job_started`: create job with `tasks` (each `status:'pending'`), status `running`, prepend to `order`.
- On `divide_task_update`: find the task by `task_id`, set its `status`/`result`, bump `updatedAt`.
- On `divide_job_done`: set job `status` + `summary`.
- Register the 3 `wsClient.on(...)` handlers once with an `_initialized` guard (same as `parallelJobs.ts`).

- [ ] **Step 4: Implement the page** (`web-ui/src/pages/DivideAgentsPage.tsx`)

Mirror `ParallelAgentsPage.tsx`: header "Divide Agents" + subtitle ("collaborative work-division across module workers"); empty state (inline SVG, no emoji); one card per job (short job id, module name, status badge, request truncated); inside each card one row per task showing `id`, status badge (pending/running/done=emerald/failed=danger/skipped=muted), the `description` (truncated), `depends_on` shown as `← t1, t2` when present, and `result` on done; job footer shows `summary`. Match `web-ui/DESIGN.md` tokens; `cursor-pointer`, focus states, responsive, `prefers-reduced-motion`.

- [ ] **Step 5: Wire route + nav**

In `App.tsx` add `<Route path="/divide" element={<AuthGuard><DivideAgentsPage/></AuthGuard>}/>` (mirror the `/parallel` route). In `AppNavBar.tsx` add a "Divide" `<Link to="/divide">` mirroring the "Parallel" link's classes/active-state.

- [ ] **Step 6: Build to verify**

Run: `cd web-ui && pnpm build`
Expected: `tsc && vite build` passes with zero type errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add web-ui/src/types/index.ts web-ui/src/stores/divideJobs.ts web-ui/src/pages/DivideAgentsPage.tsx web-ui/src/App.tsx web-ui/src/components/Layout/AppNavBar.tsx
git commit -m "feat(web-ui): divide-work tracking page + live ws store"
```

---

### Task 9: Full suite + lint + e2e

**Files:** none (verification). Per CLAUDE.md: unit tests AND a real run with `OPENAI_API_KEY`.

- [ ] **Step 1: Run the full divide suite**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/divide/ -q`
Expected: all pass.

- [ ] **Step 2: Run the project suite + interpret**

Run: `ENVIRONMENT=pytest .venv/bin/pytest -q`
Expected: no NEW failures referencing `divide` vs the pre-existing baseline (project has pre-existing PgSessionManager-migration failures; confirm none of the new failures reference `atria/core/divide` or `tests/core/divide`).

- [ ] **Step 3: Lint the new files**

Run: `uvx ruff check atria/core/divide tests/core/divide atria/core/agents/subagents/agents/module_worker.py`
Expected: All checks passed (fix any issues in the new files only).

- [ ] **Step 4: Real e2e (deferred runbook if no infra)**

```bash
export OPENAI_API_KEY="…"
redis-server                                  # Redis up
# Start a TaskIQ worker with concurrency >= 2 (REQUIRED for nested dispatch):
#   <project worker launch cmd> --max-async-tasks 4
make run                                       # or: atria run ui
```
On a module (e.g. `item_flow_tracking`), chat a decomposable request. Verify: (a) `divide_work` returns `job_id`; (b) the `/divide` page shows the task DAG with statuses streaming; (c) some tasks run in parallel, dependents wait; (d) a failed task's dependents show `skipped`, independent tasks still finish; (e) module data reflects the workers' writes; (f) the final summary returns to chat. If Redis/worker/API key are unavailable in this environment, record this step as DEFERRED with the runbook above (do not claim it passed).

- [ ] **Step 5: Commit (if any fixups)**

```bash
git add -A
git commit -m "test(divide): verify work-division end-to-end"
```

---

## Self-Review

**Spec coverage**
- Operational work-division on one module → Tasks 5/6 (orchestrator + tools). ✓
- LLM decompose → DAG with mixed deps → Task 2. ✓
- Dependency-aware scheduling + skip-on-fail → Task 3. ✓
- Uniform all-dispatch, autonomous (no approval) → workers are background subagents (Task 4) enqueued by the orchestrator (Task 5); no approval path anywhere. ✓
- Shared context = module data (working_dir = modules root, shared SQLite) + blackboard (`dw_{job}` on the payload) → Tasks 5. ✓
- Redis job store + config → Task 1. ✓
- Tools + registry wiring (mirror parallel) → Task 6. ✓
- WS events + frontend `/divide` → Tasks 7/8. ✓
- Graceful degradation (soft tool errors, job `failed`, never raises) → Tasks 2/3/5/6. ✓
- Concurrency ≥ 2 constraint + timeout → documented in Global Constraints + Task 9 runbook; the task-client-driven loop (Task 6 note) sidesteps the nested-slot deadlock by running the loop on the agent's own client loop. ✓
- Testing unit + e2e → Task 9. ✓

**Placeholder scan:** No "TBD/TODO". Integration tasks (6 registry/definitions, 8 frontend) carry concrete grep/`cat` anchors to existing siblings (`parallel/tools.py`, `_get_parallel_orchestrator`, the shipped `/parallel` files) plus full code for all new logic. Task 6 explicitly resolves the coordinator-task ambiguity (run the loop on the agent's task client; drop the separate `tasks.py`).

**Type consistency:** `DivideTask`/`DivideJob` fields and statuses identical across T1/T3/T5/T8. `decompose(request, module_skill, llm_call, max_tasks)` consistent (T2,T5). `schedule(tasks, enqueue, await_one, max_parallel, on_change)` consistent (T3,T5). `DivideOrchestrator(...)` + `start`/`collect`/`start_async`/`collect_async` consistent (T5,T6). `execute_divide_work(arguments, orchestrator, module, module_skill)` / `execute_get_divide_result(arguments, orchestrator)` consistent (T6). `on_divide_event(stage, data)` + the three `divide_*` WS types consistent (T5,T7,T8). `subagent_type="module_worker"` consistent (T4,T5).
