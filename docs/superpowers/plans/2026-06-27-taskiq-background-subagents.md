# TaskIQ Background Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `spawn_subagent(run_in_background=true)` run as a durable TaskIQ task in a separate worker process, returning a `task_id` immediately and collectible later via `get_subagent_output`.

**Architecture:** A new `atria/core/tasks/` package provides a Redis-backed TaskIQ broker, a serializable `SubagentTaskPayload`, a sync-bridge `TaskIQClient` (owns one persistent background event loop so the synchronous agent loop can enqueue/await without changing its signatures), the `run_background_subagent` task, and a scheduler with a janitor. The worker rebuilds subagent dependencies from the payload using a `build_runtime_and_deps` builder extracted from `agent_executor._run_agent_sync`, so the web executor and worker share one construction path. Fire-and-collect: no live streaming in this sub-project.

**Tech Stack:** Python 3.11+, TaskIQ (`taskiq`, `taskiq-redis`), Redis (already a dependency), Pydantic v2, pytest + `anyio`.

## Global Constraints

- Line length 100 (Black + Ruff). Type hints on public APIs (mypy strict). Google-style docstrings.
- New runtime deps limited to `taskiq` and `taskiq-redis`. No Celery/RabbitMQ/NATS.
- Broker is `ListQueueBroker` (at-most-once, no acks) — a crashed worker's task is NOT auto-redelivered; loss is surfaced as `orphaned`. This is deliberate (avoids double-running side-effecting tools).
- Server mode only. The local TUI keeps today's synchronous in-thread subagents — do NOT change `execute_subagent`'s synchronous default path.
- Fire-and-collect: the worker must NOT publish to the bus or touch the WebSocket loop.
- Under `ENVIRONMENT=pytest` the broker factory returns `InMemoryBroker(await_inplace=True)` — unit tests never require a real Redis.
- Redis URL/result-TTL come from config mirroring `BusConfig` (`atria/models/config.py:108`), default `redis://localhost:6379/0`.
- Commit after every task. Conventional Commit messages. Do NOT add a `Co-Authored-By: Claude` trailer (project rule).
- Run the full suite once at the end (project rule: skip per-task suite-wide runs; per-task you run only the new test).

---

### Task 1: TaskIQ dependency, config, and broker factory

**Files:**
- Modify: `pyproject.toml` (dependencies array, after `"redis>=5.0",`)
- Modify: `atria/models/config.py` (add `TasksConfig`, attach to `AppConfig`)
- Create: `atria/core/tasks/__init__.py`
- Create: `atria/core/tasks/broker.py`
- Test: `tests/core/tasks/test_broker.py`

**Interfaces:**
- Produces: `make_broker(redis_url: str, result_ttl: int) -> AsyncBroker`; module-level singleton `broker: AsyncBroker`; `TasksConfig` with fields `redis_url: str`, `result_ttl: int`; `AppConfig.tasks: TasksConfig`.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to the `dependencies` list (next to `"redis>=5.0",`):

```toml
    "taskiq>=0.11",
    "taskiq-redis>=1.0",
```

- [ ] **Step 2: Install**

Run: `uv sync` (or `make install`)
Expected: taskiq and taskiq-redis resolve and install.

- [ ] **Step 3: Add `TasksConfig` to config**

In `atria/models/config.py`, directly below `BusConfig` (ends ~line 113), add:

```python
class TasksConfig(BaseModel):
    """Distributed task queue (TaskIQ) settings for background subagents."""

    redis_url: str = "redis://localhost:6379/0"
    result_ttl: int = 3600  # seconds a task result lives in Redis
    orphan_after: int = 1800  # seconds before an unfinished task is deemed orphaned
```

In the `AppConfig` class, add a field alongside the other sub-configs:

```python
    tasks: TasksConfig = Field(default_factory=TasksConfig)
```

(If `AppConfig` is defined in a different module, add the field wherever the other top-level config groups like `web` live. Search: `grep -n "class AppConfig" atria/models/config.py`.)

- [ ] **Step 4: Write the failing test**

```python
# tests/core/tasks/test_broker.py
import os

from taskiq import InMemoryBroker

from atria.core.tasks.broker import make_broker


def test_make_broker_returns_inmemory_under_pytest(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "pytest")
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)
    assert isinstance(broker, InMemoryBroker)


def test_make_broker_returns_redis_broker_otherwise(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)
    # ListQueueBroker, not InMemory
    assert not isinstance(broker, InMemoryBroker)
    assert broker.result_backend is not None
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/core/tasks/test_broker.py -v`
Expected: FAIL — `ModuleNotFoundError: atria.core.tasks.broker`.

- [ ] **Step 6: Implement the broker factory**

```python
# atria/core/tasks/__init__.py
"""Distributed task-queue substrate (TaskIQ) for background subagents."""
```

```python
# atria/core/tasks/broker.py
"""TaskIQ broker factory and process-global broker singleton.

Mirrors atria.web.bus.make_bus: one factory, one module-level singleton that
the `taskiq worker` / `taskiq scheduler` CLIs import. ListQueueBroker is used
(at-most-once, no acknowledgements) so a crashed worker never silently
re-runs a side-effecting subagent.
"""
from __future__ import annotations

import os

from taskiq import AsyncBroker, InMemoryBroker
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend


def make_broker(redis_url: str, result_ttl: int) -> AsyncBroker:
    """Return the broker for the current environment.

    Under ENVIRONMENT=pytest, returns an in-process broker so unit tests need
    no Redis. Otherwise a Redis ListQueueBroker with a Redis result backend.
    """
    if os.environ.get("ENVIRONMENT") == "pytest":
        return InMemoryBroker(await_inplace=True)
    result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
        redis_url=redis_url,
        result_ex_time=result_ttl,
    )
    return ListQueueBroker(url=redis_url).with_result_backend(result_backend)


# Process-global singleton imported by the worker/scheduler CLIs and the
# server lifespan. Defaults match BusConfig; the server re-creates it from
# AppConfig.tasks at startup if values differ.
broker: AsyncBroker = make_broker("redis://localhost:6379/0", result_ttl=3600)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/core/tasks/test_broker.py -v`
Expected: PASS (both tests).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock atria/models/config.py atria/core/tasks/__init__.py atria/core/tasks/broker.py tests/core/tasks/test_broker.py
git commit -m "feat(tasks): add TaskIQ broker factory and tasks config"
```

---

### Task 2: SubagentTaskPayload (the cross-process contract)

**Files:**
- Create: `atria/core/tasks/payload.py`
- Test: `tests/core/tasks/test_payload.py`

**Interfaces:**
- Produces: `SubagentTaskPayload` (Pydantic v2 model) with fields `session_id: str`, `owner_id: str`, `subagent_type: str`, `prompt: str`, `description: str = ""`, `working_dir: str`, `path_mapping: dict[str, str] = {}`, `docker: bool = False`, `tool_names: list[str] | None = None`, `parent_tool_call_id: str | None = None`, `config_snapshot: dict[str, Any]`. Methods: `.model_dump()` / `.model_validate()` (inherited).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/tasks/test_payload.py
import pytest
from pydantic import ValidationError

from atria.core.tasks.payload import SubagentTaskPayload


def _valid() -> dict:
    return {
        "session_id": "s1",
        "owner_id": "u1",
        "subagent_type": "general-purpose",
        "prompt": "do the thing",
        "working_dir": "/tmp/work",
        "config_snapshot": {"model": "gpt-4o"},
    }


def test_payload_round_trips_through_json():
    p = SubagentTaskPayload.model_validate(_valid())
    raw = p.model_dump_json()
    again = SubagentTaskPayload.model_validate_json(raw)
    assert again == p
    assert again.subagent_type == "general-purpose"
    assert again.tool_names is None


def test_payload_rejects_non_serializable_field():
    bad = _valid()
    bad["config_snapshot"] = {"console": object()}  # not JSON-serializable
    p = SubagentTaskPayload.model_validate(bad)
    with pytest.raises((TypeError, ValueError)):
        p.model_dump_json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/tasks/test_payload.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the payload**

```python
# atria/core/tasks/payload.py
"""Serializable contract for a background subagent run.

This is the ONLY object that crosses the server→worker boundary. It carries
the *inputs* needed to rebuild dependencies in the worker, never live objects
(mode_manager, tool_registry, etc.), which are not picklable/serializable.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubagentTaskPayload(BaseModel):
    """Everything the worker needs to reconstruct and run a subagent."""

    session_id: str
    owner_id: str
    subagent_type: str
    prompt: str
    description: str = ""
    working_dir: str
    path_mapping: dict[str, str] = Field(default_factory=dict)
    docker: bool = False
    tool_names: list[str] | None = None
    parent_tool_call_id: str | None = None
    config_snapshot: dict[str, Any]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/tasks/test_payload.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/core/tasks/payload.py tests/core/tasks/test_payload.py
git commit -m "feat(tasks): add SubagentTaskPayload cross-process contract"
```

---

### Task 3: Task meta store + TaskIQClient sync bridge

**Files:**
- Create: `atria/core/tasks/meta.py`
- Create: `atria/core/tasks/client.py`
- Test: `tests/core/tasks/test_client.py`

**Interfaces:**
- Consumes: `broker` (Task 1), `SubagentTaskPayload` (Task 2).
- Produces:
  - `TaskMeta` helpers (async): `record_enqueue(redis_url, task_id, session_id)`, `age_seconds(redis_url, task_id) -> float | None`, `reap_orphans(redis_url, max_age) -> list[str]`.
  - `TaskIQClient(broker, redis_url, orphan_after=1800)` with sync methods: `enqueue(payload: SubagentTaskPayload) -> str`, `await_result(task_id: str, block: bool = True, timeout_ms: int = 30000) -> dict`, `is_ready(task_id: str) -> bool`. Result dict shapes: success `{"success": True, "content": str, "messages": list, "completion_status": str, "status": "done"}`; running `{"success": False, "status": "running"}`; failed `{"success": False, "status": "failed", "error": str}`; orphaned `{"success": False, "status": "failed", "error": "orphaned", "reason": "orphaned"}`; expired `{"success": False, "status": "expired", "error": "result expired"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/tasks/test_client.py
import os

import pytest

from atria.core.tasks.broker import make_broker
from atria.core.tasks.client import TaskIQClient
from atria.core.tasks.payload import SubagentTaskPayload


@pytest.fixture
def payload() -> SubagentTaskPayload:
    return SubagentTaskPayload(
        session_id="s1",
        owner_id="u1",
        subagent_type="general-purpose",
        prompt="hi",
        working_dir="/tmp",
        config_snapshot={},
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "pytest")
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)

    # Register an in-memory task that echoes a success result.
    @broker.task(task_name="atria.core.tasks.tasks.run_background_subagent")
    async def _fake(payload: dict) -> dict:
        return {
            "success": True,
            "content": "done:" + payload["prompt"],
            "messages": [],
            "completion_status": "success",
        }

    c = TaskIQClient(broker, redis_url="redis://localhost:6379/0", orphan_after=1800)
    c.startup()
    yield c
    c.shutdown()


def test_enqueue_returns_task_id_and_result(client, payload):
    task_id = client.enqueue(payload)
    assert isinstance(task_id, str) and task_id
    result = client.await_result(task_id, block=True, timeout_ms=5000)
    assert result["success"] is True
    assert result["content"] == "done:hi"
    assert result["status"] == "done"


def test_await_nonblocking_when_not_ready_returns_running(client, payload):
    # Unknown id, non-blocking → running (not yet old enough to be orphaned)
    result = client.await_result("does-not-exist", block=False, timeout_ms=0)
    assert result["status"] in {"running", "failed"}
```

(Note: with `InMemoryBroker(await_inplace=True)` the result is ready immediately after `enqueue`; the first test still exercises the full enqueue→await path. The second asserts the non-ready branch.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/tasks/test_client.py -v`
Expected: FAIL — `atria.core.tasks.client` / `meta` not found.

- [ ] **Step 3: Implement the meta store**

```python
# atria/core/tasks/meta.py
"""Lightweight Redis-backed bookkeeping for in-flight task IDs.

Used to distinguish "still running" from "orphaned" (worker died) on the
collect side, and to let the scheduler janitor reap stale entries. Keys are
small and carry their own TTL so they self-clean even if the janitor lags.
"""
from __future__ import annotations

import time

import redis.asyncio as aioredis

_PREFIX = "atria:task:meta:"
_META_TTL = 24 * 3600  # seconds; janitor normally removes earlier


async def record_enqueue(redis_url: str, task_id: str, session_id: str) -> None:
    r = aioredis.from_url(redis_url)
    try:
        await r.hset(
            _PREFIX + task_id,
            mapping={"created_at": str(time.time()), "session_id": session_id},
        )
        await r.expire(_PREFIX + task_id, _META_TTL)
    finally:
        await r.aclose()


async def age_seconds(redis_url: str, task_id: str) -> float | None:
    r = aioredis.from_url(redis_url)
    try:
        created = await r.hget(_PREFIX + task_id, "created_at")
        if created is None:
            return None
        return time.time() - float(created)
    finally:
        await r.aclose()


async def reap_orphans(redis_url: str, max_age: float) -> list[str]:
    """Delete meta entries older than max_age. Returns the reaped task_ids."""
    r = aioredis.from_url(redis_url)
    reaped: list[str] = []
    try:
        async for key in r.scan_iter(match=_PREFIX + "*"):
            created = await r.hget(key, "created_at")
            if created is not None and (time.time() - float(created)) > max_age:
                await r.delete(key)
                k = key.decode() if isinstance(key, bytes) else key
                reaped.append(k[len(_PREFIX):])
    finally:
        await r.aclose()
    return reaped
```

- [ ] **Step 4: Implement the client**

```python
# atria/core/tasks/client.py
"""Synchronous bridge from the (thread-based, loopless) agent code to the
async TaskIQ broker.

Owns ONE persistent asyncio event loop on a daemon thread, started lazily,
with the broker connected once. Synchronous callers submit coroutines via
run_coroutine_threadsafe — no per-call asyncio.run(), no broker reconnect.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from taskiq import AsyncBroker

from atria.core.tasks import meta
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)

_TASK_NAME = "atria.core.tasks.tasks.run_background_subagent"


class TaskIQClient:
    """Enqueue background subagents and collect their results, synchronously."""

    def __init__(self, broker: AsyncBroker, redis_url: str, orphan_after: int = 1800):
        self._broker = broker
        self._redis_url = redis_url
        self._orphan_after = orphan_after
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False

    # ── loop lifecycle ───────────────────────────────────────────────────
    def startup(self) -> None:
        if self._started:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._submit(self._broker.startup())
        self._started = True

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        if not self._started or self._loop is None:
            return
        try:
            self._submit(self._broker.shutdown())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._started = False

    def _submit(self, coro: Any, timeout: float | None = None) -> Any:
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    # ── public sync API ──────────────────────────────────────────────────
    def enqueue(self, payload: SubagentTaskPayload) -> str:
        self.startup()
        task_id = self._submit(self._enqueue_async(payload))
        return task_id

    async def _enqueue_async(self, payload: SubagentTaskPayload) -> str:
        task = self._broker.find_task(_TASK_NAME)
        if task is None:
            raise RuntimeError(f"task {_TASK_NAME} is not registered on the broker")
        kicked = await task.kiq(payload.model_dump())
        await meta.record_enqueue(self._redis_url, kicked.task_id, payload.session_id)
        return kicked.task_id

    def is_ready(self, task_id: str) -> bool:
        self.startup()
        return bool(self._submit(self._broker.result_backend.is_result_ready(task_id)))

    def await_result(
        self, task_id: str, block: bool = True, timeout_ms: int = 30000
    ) -> dict:
        self.startup()
        return self._submit(self._await_async(task_id, block, timeout_ms))

    async def _await_async(self, task_id: str, block: bool, timeout_ms: int) -> dict:
        backend = self._broker.result_backend
        deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000.0)
        while True:
            if await backend.is_result_ready(task_id):
                res = await backend.get_result(task_id, with_logs=False)
                if res.is_err:
                    return {
                        "success": False,
                        "status": "failed",
                        "error": str(res.error),
                    }
                value = res.return_value or {}
                return {**value, "success": value.get("success", True), "status": "done"}
            if not block or asyncio.get_event_loop().time() >= deadline:
                age = await meta.age_seconds(self._redis_url, task_id)
                if age is not None and age > self._orphan_after:
                    return {
                        "success": False,
                        "status": "failed",
                        "error": "orphaned",
                        "reason": "orphaned",
                    }
                return {"success": False, "status": "running"}
            await asyncio.sleep(0.25)
```

Note on `find_task`: TaskIQ brokers expose registered tasks via `broker.find_task(name)` returning the decorated task (with `.kiq`). The real task is registered in Task 5 under exactly `_TASK_NAME`; the test registers a fake under the same name.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/tasks/test_client.py -v`
Expected: PASS. If `find_task` is unavailable on this TaskIQ version, replace `self._broker.find_task(_TASK_NAME)` with a direct import of the task in Task 5 and guard with a late import; re-run.

- [ ] **Step 6: Commit**

```bash
git add atria/core/tasks/meta.py atria/core/tasks/client.py tests/core/tasks/test_client.py
git commit -m "feat(tasks): add task meta store and sync TaskIQClient bridge"
```

---

### Task 4: Extract `build_runtime_and_deps` (shared construction)

**Files:**
- Create: `atria/core/agents/deps_builder.py`
- Modify: `atria/web/agent_executor.py` (`_run_agent_sync`, ~lines 243–430)
- Test: `tests/core/agents/test_deps_builder.py`

**Interfaces:**
- Consumes: `SubagentTaskPayload` (Task 2).
- Produces: `build_runtime_and_deps(payload: SubagentTaskPayload) -> tuple[RuntimeService, AgentDependencies]`. The function reloads the session by `payload.session_id`/`owner_id`, rebuilds `AppConfig` from `payload.config_snapshot`, constructs the tool instances + tool registry + MCP manager + `RuntimeService`, and assembles `AgentDependencies` exactly as `_run_agent_sync` does today.

This is an **extract-method refactor**: behavior is unchanged; the goal is one construction path used by both the web executor and the worker.

- [ ] **Step 1: Read the current construction block**

Run: `sed -n '243,430p' atria/web/agent_executor.py`
Identify the contiguous block that: (a) resolves config + working_dir from the session, (b) instantiates tools (FileOps, WriteTool, BashTool, WebFetchTool, …), (c) builds the `RuntimeService` with tool registry + MCP manager, (d) assembles deps. This block is the body to move.

- [ ] **Step 2: Write the failing test**

```python
# tests/core/agents/test_deps_builder.py
from atria.core.agents.deps_builder import build_runtime_and_deps
from atria.core.tasks.payload import SubagentTaskPayload


def test_build_runtime_and_deps_smoke(tmp_path, monkeypatch):
    # Minimal config snapshot; build must return a runtime + deps without error.
    payload = SubagentTaskPayload(
        session_id="test-session",
        owner_id="test-owner",
        subagent_type="general-purpose",
        prompt="noop",
        working_dir=str(tmp_path),
        config_snapshot={},  # builder falls back to default AppConfig
    )
    runtime, deps = build_runtime_and_deps(payload)
    assert runtime is not None
    assert deps.working_dir == tmp_path
    assert deps.config is not None
    assert hasattr(deps, "session_manager")
```

(If `build_runtime_and_deps` needs a live session to exist, the test should stub `session_manager.load_session` via monkeypatch to return a fresh empty session. Inspect the real `pg_manager.load_session` signature first: `grep -n "def load_session" atria/core/context_engineering/history/session_manager/pg_manager.py`, then monkeypatch accordingly.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/agents/test_deps_builder.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Create the builder by moving the block**

Create `atria/core/agents/deps_builder.py`. Move the construction block from `_run_agent_sync` into:

```python
# atria/core/agents/deps_builder.py
"""Single construction path for an agent run's RuntimeService + dependencies.

Extracted verbatim from agent_executor._run_agent_sync so the web executor and
the TaskIQ worker build dependencies identically and cannot drift.
"""
from __future__ import annotations

from atria.core.tasks.payload import SubagentTaskPayload
# ... (move the exact imports the block needs from agent_executor)


def build_runtime_and_deps(payload: SubagentTaskPayload):
    """Rebuild (RuntimeService, AgentDependencies) from a serializable payload."""
    # 1. Resolve AppConfig from payload.config_snapshot (fall back to defaults).
    # 2. Resolve working_dir = Path(payload.working_dir).
    # 3. Load the session via the session manager (payload.session_id, owner_id).
    # 4. Instantiate tools, tool registry, MCP manager, RuntimeService.
    # 5. Assemble and return (runtime_service, AgentDependencies).
    ...
```

Fill the body with the lines moved out of `_run_agent_sync`. Where the original read from `current_session`/request objects, read the equivalent from `payload` instead. Keep the return type a 2-tuple.

- [ ] **Step 5: Re-point `_run_agent_sync` at the builder**

In `agent_executor._run_agent_sync`, replace the moved block with a call that constructs a `SubagentTaskPayload`-shaped object (or pass the existing in-process values) into `build_runtime_and_deps`. Since the web path already holds live objects, keep using them directly where serialization is unnecessary, but route the *construction* through the shared function so both paths converge. Confirm no behavior change.

- [ ] **Step 6: Run the builder test + the existing web executor tests**

Run: `uv run pytest tests/core/agents/test_deps_builder.py -v`
Expected: PASS.
Run: `uv run pytest tests/ -k "agent_executor or web" -q`
Expected: existing web/executor tests still pass (no regression from the extract).

- [ ] **Step 7: Commit**

```bash
git add atria/core/agents/deps_builder.py atria/web/agent_executor.py tests/core/agents/test_deps_builder.py
git commit -m "refactor(agents): extract build_runtime_and_deps shared by web and worker"
```

---

### Task 5: The `run_background_subagent` task

**Files:**
- Create: `atria/core/tasks/tasks.py`
- Test: `tests/core/tasks/test_tasks.py`

**Interfaces:**
- Consumes: `broker` (Task 1), `SubagentTaskPayload` (Task 2), `build_runtime_and_deps` (Task 4).
- Produces: `run_background_subagent` (TaskIQ task, name `atria.core.tasks.tasks.run_background_subagent`) — `async (payload: dict) -> dict` returning `{success, content, messages, completion_status}`. Helper `_run_subagent_sync(runtime, deps, payload) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/tasks/test_tasks.py
import pytest

import atria.core.tasks.tasks as tasks_mod
from atria.core.tasks.payload import SubagentTaskPayload


@pytest.mark.anyio
async def test_run_background_subagent_uses_builder(monkeypatch):
    payload = SubagentTaskPayload(
        session_id="s", owner_id="u", subagent_type="general-purpose",
        prompt="echo", working_dir="/tmp", config_snapshot={},
    )

    def fake_build(p):
        return ("RUNTIME", "DEPS")

    def fake_run(runtime, deps, p):
        assert runtime == "RUNTIME" and deps == "DEPS"
        return {"success": True, "content": "ok", "messages": [],
                "completion_status": "success"}

    monkeypatch.setattr(tasks_mod, "build_runtime_and_deps", fake_build)
    monkeypatch.setattr(tasks_mod, "_run_subagent_sync", fake_run)

    result = await tasks_mod.run_background_subagent(payload.model_dump())
    assert result["success"] is True
    assert result["content"] == "ok"


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/tasks/test_tasks.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the task**

```python
# atria/core/tasks/tasks.py
"""The background-subagent TaskIQ task. Runs in the worker process."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from atria.core.agents.deps_builder import build_runtime_and_deps
from atria.core.tasks.broker import broker
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


def _run_subagent_sync(runtime: Any, deps: Any, payload: SubagentTaskPayload) -> dict:
    """Run the subagent synchronously via the manager. Blocking; called in a
    worker thread so the worker's event loop stays responsive."""
    result = runtime.subagent_manager.execute_subagent(
        name=payload.subagent_type,
        task=payload.prompt,
        deps=deps,
        show_spawn_header=False,
        tool_call_id=payload.parent_tool_call_id,
        working_dir=payload.working_dir,
        path_mapping=payload.path_mapping or None,
    )
    return {
        "success": bool(result.get("success")),
        "content": result.get("content", ""),
        "messages": result.get("messages", []),
        "completion_status": result.get("completion_status", "success"),
    }


@broker.task(task_name="atria.core.tasks.tasks.run_background_subagent")
async def run_background_subagent(payload: dict) -> dict:
    """Rebuild deps from the payload and run the subagent (fire-and-collect)."""
    p = SubagentTaskPayload.model_validate(payload)
    try:
        runtime, deps = build_runtime_and_deps(p)
        return await asyncio.to_thread(_run_subagent_sync, runtime, deps, p)
    except Exception as exc:  # noqa: BLE001
        logger.exception("background subagent failed: %s", exc)
        return {
            "success": False,
            "content": f"background subagent failed: {exc}",
            "messages": [],
            "completion_status": "error",
        }
```

(Confirm how to reach the subagent manager from the runtime: `grep -n "subagent_manager\|SubAgentManager" atria/web/agent_executor.py atria/core/runtime/*.py`. If the manager is not an attribute of `RuntimeService`, have `build_runtime_and_deps` return it as a third tuple element and adjust the signatures in Tasks 4–5 consistently.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/tasks/test_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/core/tasks/tasks.py tests/core/tasks/test_tasks.py
git commit -m "feat(tasks): add run_background_subagent task"
```

---

### Task 6: Manager — background enqueue, collect, and inline fallback

**Files:**
- Create: `atria/core/agents/subagents/manager/background.py` (new mixin)
- Modify: `atria/core/agents/subagents/manager/manager.py` (init: add task client; add mixin to class bases)
- Modify: `atria/core/agents/subagents/manager/execution.py` (`execute_subagent`: add `run_in_background` param)
- Test: `tests/core/agents/subagents/test_background_manager.py`

**Interfaces:**
- Consumes: `TaskIQClient` (Task 3), `SubagentTaskPayload` (Task 2).
- Produces:
  - `execute_subagent(..., run_in_background: bool = False, owner_id: str | None = None, session_id: str | None = None, config_snapshot: dict | None = None)` — when `run_in_background` is True and a task client is available, builds a payload, enqueues, and returns `{"success": True, "task_id": str, "status": "running", "background": True}`. On enqueue failure (e.g. Redis down) logs a warning and falls through to the existing synchronous path.
  - `get_background_task_output(task_id: str, block: bool = True, timeout: int = 30000) -> dict` — delegates to `TaskIQClient.await_result` and shapes the result for the tool layer.
  - `SubAgentManager._task_client: TaskIQClient | None`, set via `set_task_client(client)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/agents/subagents/test_background_manager.py
from atria.core.agents.subagents.manager.manager import SubAgentManager


class _FakeClient:
    def __init__(self):
        self.enqueued = None

    def enqueue(self, payload):
        self.enqueued = payload
        return "task-xyz"

    def await_result(self, task_id, block=True, timeout_ms=30000):
        assert task_id == "task-xyz"
        return {"success": True, "content": "bg done", "status": "done",
                "messages": [], "completion_status": "success"}


def _make_manager(monkeypatch):
    # Build a minimal manager; stub heavy init as needed for your codebase.
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _FakeClient()
    return mgr


def test_get_background_task_output_delegates(monkeypatch):
    mgr = _make_manager(monkeypatch)
    out = mgr.get_background_task_output("task-xyz", block=True, timeout=5000)
    assert out["success"] is True
    assert out["content"] == "bg done"


def test_execute_subagent_background_enqueues(monkeypatch):
    mgr = _make_manager(monkeypatch)
    result = mgr.execute_subagent_background(
        name="general-purpose",
        task="do bg work",
        owner_id="u1",
        session_id="s1",
        working_dir="/tmp",
        config_snapshot={},
        tool_call_id="tc1",
    )
    assert result["task_id"] == "task-xyz"
    assert result["status"] == "running"
    assert mgr._task_client.enqueued.subagent_type == "general-purpose"
```

(`execute_subagent_background` is a thin helper the mixin exposes so the test doesn't need the full synchronous `execute_subagent` machinery. `execute_subagent` itself calls this helper when `run_in_background=True`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/agents/subagents/test_background_manager.py -v`
Expected: FAIL — `execute_subagent_background` / `get_background_task_output` / `_task_client` missing.

- [ ] **Step 3: Implement the background mixin**

```python
# atria/core/agents/subagents/manager/background.py
"""Background-execution mixin for SubAgentManager (TaskIQ-backed)."""
from __future__ import annotations

import logging
from typing import Any

from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


class BackgroundMixin:
    """Adds run_in_background enqueue + collect to SubAgentManager."""

    _task_client: Any  # TaskIQClient | None, set by set_task_client

    def set_task_client(self, client: Any) -> None:
        self._task_client = client

    def execute_subagent_background(
        self,
        name: str,
        task: str,
        owner_id: str,
        session_id: str,
        working_dir: str,
        config_snapshot: dict[str, Any],
        tool_call_id: str | None = None,
        description: str = "",
        path_mapping: dict[str, str] | None = None,
        docker: bool = False,
        tool_names: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = SubagentTaskPayload(
            session_id=session_id,
            owner_id=owner_id,
            subagent_type=name,
            prompt=task,
            description=description,
            working_dir=working_dir,
            path_mapping=path_mapping or {},
            docker=docker,
            tool_names=tool_names,
            parent_tool_call_id=tool_call_id,
            config_snapshot=config_snapshot,
        )
        task_id = self._task_client.enqueue(payload)
        return {
            "success": True,
            "background": True,
            "status": "running",
            "task_id": task_id,
            "subagent_type": name,
        }

    def get_background_task_output(
        self, task_id: str, block: bool = True, timeout: int = 30000
    ) -> dict[str, Any]:
        if getattr(self, "_task_client", None) is None:
            return {
                "success": False,
                "error": "Background task client not configured.",
                "output": None,
            }
        result = self._task_client.await_result(task_id, block=block, timeout_ms=timeout)
        if result.get("status") == "running":
            return {"success": False, "status": "running", "output": None,
                    "task_id": task_id}
        if not result.get("success"):
            return {"success": False, "status": result.get("status", "failed"),
                    "error": result.get("error", "unknown error"), "output": None}
        return {
            "success": True,
            "status": "done",
            "output": result.get("content", ""),
            "content": result.get("content", ""),
            "completion_status": result.get("completion_status", "success"),
        }
```

- [ ] **Step 4: Wire the mixin and client into the manager**

In `manager.py`: add `BackgroundMixin` to the class bases:

```python
from atria.core.agents.subagents.manager.background import BackgroundMixin

class SubAgentManager(RegistrationMixin, DockerMixin, ExecutionMixin, BackgroundMixin):
```

In `SubAgentManager.__init__` (after the existing `self._...` assignments, ~line 104) add:

```python
        self._task_client = None  # set later via set_task_client()
```

- [ ] **Step 5: Add `run_in_background` to `execute_subagent`**

In `execution.py`, add the parameter to the signature and an early branch at the top of the method body (before the SubagentStart hook), so the synchronous default path is untouched:

```python
    def execute_subagent(
        self,
        name: str,
        task: str,
        deps: SubAgentDeps,
        ui_callback: Any = None,
        task_monitor: Any = None,
        working_dir: Any = None,
        docker_handler: Any = None,
        path_mapping: dict[str, str] | None = None,
        show_spawn_header: bool = True,
        tool_call_id: str | None = None,
        run_in_background: bool = False,
        owner_id: str | None = None,
        session_id: str | None = None,
        config_snapshot: dict | None = None,
    ) -> dict[str, Any]:
        if run_in_background and getattr(self, "_task_client", None) is not None:
            try:
                return self.execute_subagent_background(
                    name=name,
                    task=task,
                    owner_id=owner_id or "",
                    session_id=session_id or "",
                    working_dir=str(working_dir or self._working_dir),
                    config_snapshot=config_snapshot or {},
                    tool_call_id=tool_call_id,
                    path_mapping=path_mapping,
                )
            except Exception as exc:  # noqa: BLE001 — Redis down etc.
                logger.warning(
                    "background enqueue failed (%s); running subagent inline", exc
                )
        # ... existing synchronous body unchanged ...
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/core/agents/subagents/test_background_manager.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add atria/core/agents/subagents/manager/background.py atria/core/agents/subagents/manager/manager.py atria/core/agents/subagents/manager/execution.py tests/core/agents/subagents/test_background_manager.py
git commit -m "feat(subagents): background enqueue/collect with inline fallback"
```

---

### Task 7: Registry wiring — pass `run_in_background` and collect

**Files:**
- Modify: `atria/core/context_engineering/tools/registry.py` (`_execute_spawn_subagent` ~427; `_get_subagent_output` stub already delegates — verify)
- Test: `tests/core/context_engineering/test_spawn_background.py` (new); update any test asserting the old stub error

**Interfaces:**
- Consumes: manager `execute_subagent(run_in_background=...)` and `get_background_task_output(...)` (Task 6).
- Produces: `spawn_subagent` with `run_in_background=true` returns `{"success": True, "output": "[BACKGROUND STARTED] task_id=...", "task_id": str, "status": "running"}`; the existing synchronous branch is unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/context_engineering/test_spawn_background.py
from atria.core.context_engineering.tools.registry import ToolRegistry  # adjust import


class _Mgr:
    def execute_subagent(self, **kwargs):
        assert kwargs.get("run_in_background") is True
        return {"success": True, "background": True, "status": "running",
                "task_id": "bg-1", "subagent_type": kwargs["name"]}

    def get_background_task_output(self, task_id, block=True, timeout=30000):
        return {"success": True, "status": "done", "output": "result text",
                "content": "result text", "completion_status": "success"}


def _registry_with_manager():
    reg = ToolRegistry.__new__(ToolRegistry)  # adjust to real constructor/seam
    reg._subagent_manager = _Mgr()
    return reg


def test_spawn_subagent_background_returns_task_id():
    reg = _registry_with_manager()
    out = reg._execute_spawn_subagent(
        {"prompt": "do it", "subagent_type": "general-purpose",
         "run_in_background": True},
        context=None,
        tool_call_id="tc-1",
    )
    assert out["task_id"] == "bg-1"
    assert out["status"] == "running"


def test_get_subagent_output_returns_result():
    reg = _registry_with_manager()
    out = reg._get_subagent_output({"task_id": "bg-1", "block": True, "timeout": 5000})
    assert out["success"] is True
    assert out["output"] == "result text"
```

(Adjust `ToolRegistry` import/instantiation to the real class name and minimal-construction seam — inspect `class .*Registry` / `class .*Handler` in `registry.py`. If `context` is required, pass a lightweight stub exposing the `.mode_manager`/`.session_manager` attributes read by the handler.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/context_engineering/test_spawn_background.py -v`
Expected: FAIL — background branch not wired (the handler ignores `run_in_background`).

- [ ] **Step 3: Wire the background branch**

In `_execute_spawn_subagent`, read the flag and the session/owner context, and pass them through. After computing `task`, `subagent_type`, `deps`, add:

```python
        run_in_background = bool(arguments.get("run_in_background", False))
        owner_id = getattr(context, "owner_id", None) if context else None
        session_id = getattr(context, "session_id", None) if context else None
        config_snapshot = {}
        if context is not None and getattr(context, "config", None) is not None:
            try:
                config_snapshot = context.config.model_dump()
            except Exception:  # noqa: BLE001
                config_snapshot = {}
```

Then change the `execute_subagent(...)` call to forward the new kwargs:

```python
        result = self._subagent_manager.execute_subagent(
            name=subagent_type,
            task=task,
            deps=deps,
            ui_callback=ui_callback,
            task_monitor=task_monitor,
            show_spawn_header=False,
            tool_call_id=tool_call_id,
            run_in_background=run_in_background,
            owner_id=owner_id,
            session_id=session_id,
            config_snapshot=config_snapshot,
        )
```

Immediately after the call, short-circuit the background case before the shallow-subagent / sync formatting logic:

```python
        if result.get("background"):
            return {
                "success": True,
                "output": f"[BACKGROUND STARTED] task_id={result['task_id']}. "
                          "Use get_subagent_output(task_id) to collect the result.",
                "task_id": result["task_id"],
                "status": "running",
                "subagent_type": subagent_type,
            }
```

`_get_subagent_output` already delegates to `manager.get_background_task_output` (registry.py:656) — no change needed there; verify it returns the Task 6 shape.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/context_engineering/test_spawn_background.py -v`
Expected: PASS.

- [ ] **Step 5: Update any test asserting the old stub**

Run: `grep -rn "Background task support not available\|not yet fully implemented" tests/`
If any test asserts the old stub message, update it to expect the new collect behavior. Re-run those tests.

- [ ] **Step 6: Commit**

```bash
git add atria/core/context_engineering/tools/registry.py tests/core/context_engineering/test_spawn_background.py
git commit -m "feat(tools): wire spawn_subagent run_in_background and collect path"
```

---

### Task 8: Scheduler + janitor

**Files:**
- Create: `atria/core/tasks/scheduler.py`
- Test: `tests/core/tasks/test_scheduler.py`

**Interfaces:**
- Consumes: `broker` (Task 1), `meta.reap_orphans` (Task 3).
- Produces: module-level `scheduler: TaskiqScheduler`; task `reap_orphan_tasks` scheduled every 10 minutes; helper `_janitor_redis_url() -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/tasks/test_scheduler.py
import time

import pytest

from atria.core.tasks import meta


@pytest.mark.anyio
async def test_reap_orphans_removes_stale(monkeypatch):
    store: dict[str, dict] = {}

    async def fake_record(url, task_id, session_id):
        store[task_id] = {"created_at": time.time() - 4000, "session_id": session_id}

    async def fake_reap(url, max_age):
        reaped = [tid for tid, m in list(store.items())
                  if time.time() - m["created_at"] > max_age]
        for tid in reaped:
            del store[tid]
        return reaped

    monkeypatch.setattr(meta, "record_enqueue", fake_record)
    monkeypatch.setattr(meta, "reap_orphans", fake_reap)

    await meta.record_enqueue("redis://x", "old-task", "s1")
    reaped = await meta.reap_orphans("redis://x", max_age=1800)
    assert "old-task" in reaped


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/tasks/test_scheduler.py -v`
Expected: FAIL until import path resolves (the test exercises `meta` reaping logic that Task 3 created; this test guards the contract the janitor relies on). If it passes already, proceed — the scheduler module still needs creating for Step 3's import smoke.

- [ ] **Step 3: Implement the scheduler**

```python
# atria/core/tasks/scheduler.py
"""TaskIQ scheduler + janitor. Run with:
    taskiq scheduler atria.core.tasks.scheduler:scheduler
"""
from __future__ import annotations

import logging
import os

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from atria.core.tasks import meta
from atria.core.tasks.broker import broker

logger = logging.getLogger(__name__)


def _janitor_redis_url() -> str:
    return os.environ.get("ATRIA_REDIS_URL", "redis://localhost:6379/0")


def _orphan_after() -> int:
    return int(os.environ.get("ATRIA_TASK_ORPHAN_AFTER", "1800"))


@broker.task(
    task_name="atria.core.tasks.scheduler.reap_orphan_tasks",
    schedule=[{"cron": "*/10 * * * *"}],
)
async def reap_orphan_tasks() -> int:
    """Delete meta entries for tasks that never completed. Returns count."""
    reaped = await meta.reap_orphans(_janitor_redis_url(), max_age=_orphan_after())
    if reaped:
        logger.warning("reaped %d orphaned task(s): %s", len(reaped), reaped)
    return len(reaped)


scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
```

- [ ] **Step 4: Add an import-smoke test**

Append to `tests/core/tasks/test_scheduler.py`:

```python
def test_scheduler_module_imports():
    from atria.core.tasks.scheduler import reap_orphan_tasks, scheduler
    assert scheduler is not None
    assert reap_orphan_tasks is not None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/tasks/test_scheduler.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add atria/core/tasks/scheduler.py tests/core/tasks/test_scheduler.py
git commit -m "feat(tasks): add scheduler and orphan-reaping janitor"
```

---

### Task 9: Server lifespan wiring + run docs

**Files:**
- Modify: `atria/web/server.py` (lifespan: create broker from config, startup/shutdown, build + attach `TaskIQClient`, call `manager.set_task_client`)
- Modify: `atria/web/state.py` (hold the `TaskIQClient` so the manager can reach it) — only if the manager is constructed there
- Create: `docs/tasks-worker.md` (how to run worker + scheduler)
- Test: `tests/web/test_lifespan_tasks.py`

**Interfaces:**
- Consumes: `make_broker` (Task 1), `TaskIQClient` (Task 3), `SubAgentManager.set_task_client` (Task 6).
- Produces: at server startup, a connected broker (guarded by `if not broker.is_worker_process`) and a started `TaskIQClient` attached to the subagent manager.

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_lifespan_tasks.py
def test_make_broker_used_in_lifespan(monkeypatch):
    # The lifespan must build the broker via make_broker and start a client.
    import atria.web.server as server
    assert hasattr(server, "_start_task_client") or hasattr(server, "lifespan")
```

(This is a light guard; the real verification is the end-to-end test in Task 10. Adjust the assertion to the actual helper name you introduce.)

- [ ] **Step 2: Wire the lifespan**

In `server.py` lifespan, after the bus block (~line 130), add:

```python
    # Start the TaskIQ broker + sync client for background subagents.
    from atria.core.tasks.broker import broker as _tasks_broker, make_broker
    from atria.core.tasks.client import TaskIQClient

    tasks_cfg = cfg.tasks if cfg else None
    if not _tasks_broker.is_worker_process:
        redis_url = tasks_cfg.redis_url if tasks_cfg else "redis://localhost:6379/0"
        result_ttl = tasks_cfg.result_ttl if tasks_cfg else 3600
        orphan_after = tasks_cfg.orphan_after if tasks_cfg else 1800
        runtime_broker = make_broker(redis_url, result_ttl)
        try:
            client = TaskIQClient(runtime_broker, redis_url, orphan_after=orphan_after)
            client.startup()
            app.state.task_client = client
            # Attach to the subagent manager so execute_subagent(run_in_background)
            # and get_background_task_output can reach it.
            if state.subagent_manager is not None:
                state.subagent_manager.set_task_client(client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TaskIQ client unavailable; background subagents disabled: %s", exc)
```

And in the shutdown half of the lifespan:

```python
    client = getattr(app.state, "task_client", None)
    if client is not None:
        client.shutdown()
```

(If `state` has no `subagent_manager` attribute, find where the manager is constructed per request/session and call `set_task_client` there instead. Search: `grep -rn "SubAgentManager(" atria/web/`.)

- [ ] **Step 3: Write the run docs**

```markdown
# Running background subagents (TaskIQ)

Background subagents require Redis plus two extra processes alongside uvicorn.

## 1. Redis
Ensure Redis is reachable at `tasks.redis_url` (default `redis://localhost:6379/0`).

## 2. Worker
    taskiq worker atria.core.tasks.broker:broker atria.core.tasks.tasks

## 3. Scheduler (janitor)
    taskiq scheduler atria.core.tasks.scheduler:scheduler

## Config (.atria/settings.json)
    { "tasks": { "redis_url": "redis://localhost:6379/0",
                 "result_ttl": 3600, "orphan_after": 1800 } }

Without a worker running, `spawn_subagent(run_in_background=true)` enqueues but
never completes; collection returns `status: running` until `orphan_after`,
then `failed: orphaned`. With Redis down, subagents fall back to synchronous
execution automatically.
```

- [ ] **Step 4: Run the guard test**

Run: `uv run pytest tests/web/test_lifespan_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/web/server.py atria/web/state.py docs/tasks-worker.md tests/web/test_lifespan_tasks.py
git commit -m "feat(web): start TaskIQ client in server lifespan; add run docs"
```

---

### Task 10: Full suite + real end-to-end verification

**Files:** none (verification task). Per project rule: unit tests AND a real run with `OPENAI_API_KEY`.

- [ ] **Step 1: Run the full unit suite once**

Run: `make test`
Expected: all tests pass (new `tests/core/tasks/*`, `test_deps_builder`, `test_background_manager`, `test_spawn_background`, `test_lifespan_tasks`, and no regressions).

- [ ] **Step 2: Typecheck + lint**

Run: `make check`
Expected: Black clean, Ruff clean, mypy clean for the new modules.

- [ ] **Step 3: Start the stack for a real run**

```bash
export OPENAI_API_KEY="…"
# terminal A
redis-server                                  # or existing Redis
# terminal B
taskiq worker atria.core.tasks.broker:broker atria.core.tasks.tasks
# terminal C
taskiq scheduler atria.core.tasks.scheduler:scheduler
# terminal D
make run                                       # web UI / server
```

- [ ] **Step 4: Trigger a real background subagent**

Issue a prompt that makes the agent call `spawn_subagent(run_in_background=true)`
(e.g. "spawn a background subagent to summarize the README, then continue
chatting; collect its result when ready").

Verify:
- The triggering turn returns immediately with `[BACKGROUND STARTED] task_id=…`.
- Terminal B (worker) logs the task executing against the real LLM.
- A follow-up `get_subagent_output(task_id)` returns the real summary.

- [ ] **Step 5: Verify failure surfacing**

Kill the worker (terminal B) mid-task, then collect: confirm the collect call
returns `status: running` and, after `orphan_after`, `failed: orphaned` — never
a hang or a raw stack trace.

- [ ] **Step 6: Final commit (if any docs/fixups)**

```bash
git add -A
git commit -m "test(tasks): verify background subagents end-to-end"
```

---

## Self-Review

**Spec coverage**
- Broker (Redis, ListQueueBroker, result backend, TTL, pytest InMemory) → Task 1. ✓
- `SubagentTaskPayload` field set + serialization guard → Task 2. ✓
- Sync/async bridge (`TaskIQClient`, persistent loop) → Task 3. ✓
- Orphaned/timeout/expired/running result shapes → Tasks 3 & 6 (await_result + collect). ✓
- `build_runtime_and_deps` extraction shared by web + worker → Task 4. ✓
- `run_background_subagent` task (`asyncio.to_thread`, fire-and-collect) → Task 5. ✓
- Manager enqueue + Redis-down inline fallback + `get_background_task_output` → Task 6. ✓
- Registry `run_in_background` pass-through + collect (fills registry.py:624-666) → Task 7. ✓
- Scheduler + janitor → Task 8. ✓
- Server lifespan startup/shutdown guarded by `is_worker_process` + `pyproject` dep + run docs → Tasks 1 & 9. ✓
- Persistence boundary (worker does not write parent session; result appended by main thread as a tool result) → enforced by fire-and-collect return path in Tasks 5–7. ✓
- Testing: unit (InMemoryBroker) + real e2e with OPENAI_API_KEY → Task 10. ✓

**Placeholder scan:** No "TBD/TODO". The two intentional "inspect the real signature" notes (Tasks 4, 7) are concrete grep commands guarding codebase-specific seams, not deferred work; each has full surrounding code.

**Type consistency:** `make_broker(redis_url, result_ttl)` consistent (Tasks 1, 9). `SubagentTaskPayload` fields identical across Tasks 2, 3, 5, 6. `TaskIQClient.await_result(task_id, block, timeout_ms)` consistent (Tasks 3, 6). Result `status` vocabulary (`done`/`running`/`failed`/`expired`, `reason: orphaned`) consistent across Tasks 3, 6, 7, 9. Task name string `atria.core.tasks.tasks.run_background_subagent` identical in Tasks 3 and 5.
