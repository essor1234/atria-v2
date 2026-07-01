# Dispatch Rewire + Blackboard UI Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `strategy` param to `spawn_subagent` that routes to the existing DeLM divide/parallel orchestrators, and stream blackboard notes to the Dispatch page in real time so users can watch task/thread reasoning.

**Architecture:** Extend `spawn_subagent` schema and handler to branch on `strategy` between the current `SubAgentManager` path (direct) and the existing `DivideOrchestrator` / `ParallelOrchestrator` (divide, parallel). Add a best-effort Redis publish to `BlackboardStore.append`; a single web-server background task consumes a psub pattern and broadcasts `blackboard.note` events on the existing WS. Frontend extends `solverJobs` store with per-task/thread notes and renders them inline under existing rows.

**Tech Stack:** Python 3.11, asyncio, `redis.asyncio`, FastAPI, existing WS layer (`atria/web/websocket.py`), React 18, Zustand.

## Global Constraints

- Backend line length 100 (Black + Ruff), type hints on public APIs (mypy strict), Google-style docstrings.
- No hard-coded LLM control flow in agent loops; new strategy value is chosen by the LLM at call time.
- No table format in system prompts — plain prose or bullets only.
- Blackboard publish is best-effort: a publish failure must never break `BlackboardStore.append`.
- Tests must run under `uv run pytest`; end-to-end verification uses `OPENAI_API_KEY` as required by project CLAUDE.md.
- Redis pub/sub uses a single psub `atria:bb:*:notes` per web process (no per-task connection).

---

### Task 1: Blackboard publish-on-append

**Files:**
- Modify: `atria/core/blackboard/store.py`
- Test: `tests/test_blackboard_pubsub.py` (new)

**Interfaces:**
- Consumes: `redis.asyncio.Redis`-compatible client with `.publish(channel, payload)` coroutine (already passed into `BlackboardStore`).
- Produces:
  - Channel name convention: `atria:bb:{task_id}:notes`.
  - Message payload (JSON): `{"task_id": str, "thread_id": int, "type": str, "content": str, "ts": float}`.
  - Publish failure returns silently (logged at WARNING); `append` still commits the RPUSH.

- [ ] **Step 1: Write the failing test**

Create `tests/test_blackboard_pubsub.py`:
```python
"""Publish-on-append behaviour for BlackboardStore."""
from __future__ import annotations

import json
from typing import Any

import pytest

from atria.core.blackboard.models import Note
from atria.core.blackboard.store import BlackboardStore


class FakeRedis:
    def __init__(self, publish_should_fail: bool = False) -> None:
        self.rpush_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.publish_calls: list[tuple[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self._publish_fail = publish_should_fail

    async def rpush(self, key: str, *values: Any) -> int:
        self.rpush_calls.append((key, values))
        return len(values)

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    async def publish(self, channel: str, payload: str) -> int:
        if self._publish_fail:
            raise RuntimeError("redis down")
        self.publish_calls.append((channel, payload))
        return 1


@pytest.mark.asyncio
async def test_append_publishes_each_note() -> None:
    redis = FakeRedis()
    store = BlackboardStore(redis, task_id="bb_abc", ttl=60)
    notes = [
        Note(type="fact", content="hello", thread_id=1, ts=1.0),
        Note(type="decision", content="choose A", thread_id=1, ts=2.0),
    ]

    await store.append(notes)

    assert len(redis.publish_calls) == 2
    channels = {c for c, _ in redis.publish_calls}
    assert channels == {"atria:bb:bb_abc:notes"}
    payload = json.loads(redis.publish_calls[0][1])
    assert payload == {
        "task_id": "bb_abc",
        "thread_id": 1,
        "type": "fact",
        "content": "hello",
        "ts": 1.0,
    }


@pytest.mark.asyncio
async def test_append_survives_publish_failure() -> None:
    redis = FakeRedis(publish_should_fail=True)
    store = BlackboardStore(redis, task_id="bb_xyz", ttl=60)

    await store.append([Note(type="fact", content="x", thread_id=0, ts=0.0)])

    assert len(redis.rpush_calls) == 1  # append still committed
    assert redis.publish_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_blackboard_pubsub.py -v`
Expected: FAIL — publish never called (feature not yet implemented).

- [ ] **Step 3: Add publish-on-append**

Modify `atria/core/blackboard/store.py`, replacing the `append` method:
```python
    async def append(self, notes: list[Note]) -> None:
        """RPUSH each note as JSON, refresh the TTL, and publish each note.

        Publish failures are swallowed (logged) so an append never fails when the
        pub/sub pipeline is unavailable — the digest still commits.
        """
        if not notes:
            return
        payloads = [json.dumps(n.to_dict()) for n in notes]
        await self._redis.rpush(self._key, *payloads)  # type: ignore[attr-defined]
        await self._redis.expire(self._key, self._ttl)  # type: ignore[attr-defined]

        task_id = self._key.removeprefix(_PREFIX)
        channel = f"{self._key}:notes"
        for note in notes:
            event = {
                "task_id": task_id,
                "thread_id": note.thread_id,
                "type": note.type,
                "content": note.content,
                "ts": note.ts,
            }
            try:
                await self._redis.publish(channel, json.dumps(event))  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 — best-effort; never break append
                _log.warning("blackboard publish failed on %s: %s", channel, exc)
```

Add at the top of the file, after the existing imports:
```python
import logging

_log = logging.getLogger(__name__)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_blackboard_pubsub.py -v`
Expected: PASS — both cases green.

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/store.py tests/test_blackboard_pubsub.py
git commit -m "feat(blackboard): publish notes to redis pub/sub on append

Best-effort publish to atria:bb:{task_id}:notes so downstream
subscribers (web) can stream notes without polling."
```

---

### Task 2: Add `strategy` field to `spawn_subagent` schema

**Files:**
- Modify: `atria/core/agents/subagents/task_tool.py`
- Test: `tests/test_task_tool_schema.py` (new)

**Interfaces:**
- Produces: `spawn_subagent` schema with an added optional field `strategy: "direct" | "divide" | "parallel"` (default `"direct"`). `subagent_type` remains in the schema but its `required` status is unchanged in the schema (still `required`); the handler in Task 3 relaxes semantics per strategy.

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_tool_schema.py`:
```python
"""Schema shape for spawn_subagent after the strategy rewire."""
from __future__ import annotations

from atria.core.agents.subagents.task_tool import create_task_tool_schema


class _FakeConfig:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class _FakeManager:
    def get_agent_configs(self) -> list[_FakeConfig]:
        return [_FakeConfig("solver", "Race worktree solvers.")]


def test_strategy_field_is_present() -> None:
    schema = create_task_tool_schema(_FakeManager())
    props = schema["function"]["parameters"]["properties"]

    assert "strategy" in props
    assert props["strategy"]["type"] == "string"
    assert set(props["strategy"]["enum"]) == {"direct", "divide", "parallel"}
    assert props["strategy"].get("default") == "direct"


def test_strategy_not_required() -> None:
    schema = create_task_tool_schema(_FakeManager())
    required = schema["function"]["parameters"]["required"]
    assert "strategy" not in required
    assert "subagent_type" in required  # unchanged: still required in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_tool_schema.py -v`
Expected: FAIL — `strategy` not in properties.

- [ ] **Step 3: Add strategy to schema**

In `atria/core/agents/subagents/task_tool.py`, inside the `properties` dict returned by `create_task_tool_schema`, add:
```python
                    "strategy": {
                        "type": "string",
                        "enum": ["direct", "divide", "parallel"],
                        "default": "direct",
                        "description": (
                            "How to dispatch this delegation. 'direct' (default) runs "
                            "one subagent via SubAgentManager (current behavior). "
                            "'divide' decomposes the prompt into a DAG and runs the "
                            "subtasks via DivideOrchestrator. 'parallel' races N "
                            "worktree-isolated solvers via ParallelOrchestrator and "
                            "applies the judge-chosen winner. For 'divide' and "
                            "'parallel', subagent_type is treated as an optional hint."
                        ),
                    },
```

Update the tool description block (append to `TASK_TOOL_DESCRIPTION`) with:
```
## Strategy

- `direct` (default): single subagent, current behavior. Best for quick, focused
  delegation of a self-contained task to one of the specialized agent types.
- `divide`: decompose the prompt into a small DAG and run the pieces via the
  divide orchestrator. Pick this when the work has multiple dependent steps
  that would benefit from being planned out and executed as a unit.
- `parallel`: fan out N worktree-isolated solvers on the same prompt and let
  the judge pick and apply the winning diff. Pick this for one well-scoped
  task where racing a few candidate approaches is worth the overhead.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_task_tool_schema.py -v`
Expected: PASS — both cases green.

- [ ] **Step 5: Commit**

```bash
git add atria/core/agents/subagents/task_tool.py tests/test_task_tool_schema.py
git commit -m "feat(spawn_subagent): add strategy field (direct|divide|parallel)"
```

---

### Task 3: Dispatch handler branches (divide + parallel)

**Files:**
- Modify: `atria/core/context_engineering/tools/registry_mixins/subagent_ops.py`
- Test: `tests/test_subagent_dispatch.py` (new)

**Interfaces:**
- Consumes:
  - `strategy` from `arguments` (default `"direct"`).
  - `context.divide_orchestrator: DivideOrchestrator | None` and `context.parallel_orchestrator: ParallelOrchestrator | None` — both may be `None` when redis/docker not configured.
- Produces (result dict for dispatch strategies):
  - Success: `{"success": True, "output": str, "job_id": str, "strategy": str}`.
  - Missing orchestrator: `{"success": False, "error": "<hint to retry with strategy=direct>", "output": None}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_subagent_dispatch.py`:
```python
"""Strategy routing in _execute_spawn_subagent."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from atria.core.context_engineering.tools.registry_mixins.subagent_ops import (
    SubagentOpsMixin,
)


class _Holder(SubagentOpsMixin):
    def __init__(self, subagent_manager=None, file_ops=None) -> None:
        self._subagent_manager = subagent_manager
        self.file_ops = file_ops


def _ctx(**kw):
    base = dict(
        mode_manager=None,
        approval_manager=None,
        undo_manager=None,
        session_manager=None,
        ui_callback=None,
        task_monitor=None,
        divide_orchestrator=None,
        parallel_orchestrator=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_direct_strategy_calls_subagent_manager() -> None:
    mgr = MagicMock()
    mgr.execute_subagent.return_value = {"success": True, "content": "ok", "messages": []}
    holder = _Holder(subagent_manager=mgr)

    result = holder._execute_spawn_subagent(
        {"description": "d", "prompt": "task", "subagent_type": "solver"},
        context=_ctx(),
    )

    mgr.execute_subagent.assert_called_once()
    assert result["success"] is True


def test_divide_strategy_calls_divide_orchestrator() -> None:
    div = MagicMock()
    div.start.return_value = "job_div_1"
    div.collect.return_value = {"status": "done", "summary": "3/3 tasks done"}
    holder = _Holder(subagent_manager=MagicMock())

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "big task",
            "subagent_type": "solver",
            "strategy": "divide",
        },
        context=_ctx(divide_orchestrator=div),
    )

    div.start.assert_called_once()
    assert result["success"] is True
    assert result["job_id"] == "job_div_1"
    assert result["strategy"] == "divide"


def test_parallel_strategy_calls_parallel_orchestrator() -> None:
    par = MagicMock()
    par.start.return_value = "job_par_1"
    par.collect.return_value = {"status": "done", "applied": True, "reasoning": "r"}
    holder = _Holder(subagent_manager=MagicMock(), file_ops=SimpleNamespace(working_dir="."))

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "solve X",
            "subagent_type": "solver",
            "strategy": "parallel",
        },
        context=_ctx(parallel_orchestrator=par),
    )

    par.start.assert_called_once()
    assert result["success"] is True
    assert result["job_id"] == "job_par_1"
    assert result["strategy"] == "parallel"


def test_dispatch_strategy_without_orchestrator_returns_fallback_hint() -> None:
    holder = _Holder(subagent_manager=MagicMock())

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "x",
            "subagent_type": "solver",
            "strategy": "divide",
        },
        context=_ctx(),  # divide_orchestrator is None
    )

    assert result["success"] is False
    assert "strategy=\"direct\"" in result["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_subagent_dispatch.py -v`
Expected: FAIL — dispatch branches not implemented (all four cases fail).

- [ ] **Step 3: Add strategy branches to `_execute_spawn_subagent`**

At the top of `_execute_spawn_subagent` in `atria/core/context_engineering/tools/registry_mixins/subagent_ops.py`, after the `task = arguments.get("prompt") or description` line, add:
```python
        strategy = (arguments.get("strategy") or "direct").lower()
        if strategy not in ("direct", "divide", "parallel"):
            return {
                "success": False,
                "error": f"unknown strategy {strategy!r}; expected direct|divide|parallel",
                "output": None,
            }

        if strategy != "direct":
            return self._dispatch_via_orchestrator(strategy, task, subagent_type, context)
```

Then add the new helper method on the mixin:
```python
    def _dispatch_via_orchestrator(
        self,
        strategy: str,
        task: str,
        subagent_type_hint: str,
        context: Any,
    ) -> dict[str, Any]:
        """Route the delegation through the divide or parallel orchestrator."""
        if strategy == "divide":
            orch = getattr(context, "divide_orchestrator", None)
            if orch is None:
                return {
                    "success": False,
                    "error": (
                        "divide orchestrator not configured (redis unavailable). "
                        "Retry with strategy=\"direct\"."
                    ),
                    "output": None,
                }
            try:
                job_id = orch.start(task, subagent_type_hint, subagent_type_hint)
                rec = orch.collect(job_id)
                summary = rec.get("summary") or rec.get("status") or ""
            except Exception as exc:  # noqa: BLE001 — surface to LLM as tool error
                return {
                    "success": False,
                    "error": f"divide dispatch failed: {exc}",
                    "output": None,
                }
            return {
                "success": True,
                "output": f"[divide {job_id}] {summary}",
                "job_id": job_id,
                "strategy": "divide",
            }

        # strategy == "parallel"
        orch = getattr(context, "parallel_orchestrator", None)
        if orch is None:
            return {
                "success": False,
                "error": (
                    "parallel orchestrator not configured (redis/docker "
                    "unavailable). Retry with strategy=\"direct\"."
                ),
                "output": None,
            }
        try:
            repo_dir = self._get_repo_dir()
            _sess = getattr(context, "session_manager", None)
            _cur = getattr(_sess, "current_session", None) if _sess else None
            owner_id = (getattr(_cur, "owner_id", "") or "") if _cur else ""
            session_id = str(getattr(_cur, "session_id", "") or "") if _cur else ""
            job_id = orch.start(task, 0, repo_dir, owner_id, session_id)
            rec = orch.collect(job_id)
            reasoning = rec.get("reasoning") or ""
            applied = rec.get("applied")
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "error": f"parallel dispatch failed: {exc}",
                "output": None,
            }
        return {
            "success": True,
            "output": f"[parallel {job_id}] applied={applied} — {reasoning}",
            "job_id": job_id,
            "strategy": "parallel",
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_subagent_dispatch.py -v`
Expected: PASS — all four cases green.

- [ ] **Step 5: Wire orchestrators onto the tool context**

Grep for the class that builds the `ToolExecutionContext`:
```bash
grep -rn "class ToolExecutionContext\|ui_callback=" atria/core --include="*.py" | head
```
Add `divide_orchestrator` and `parallel_orchestrator` fields (both `Any | None = None`) alongside the existing `mode_manager` / `approval_manager` etc. Pass through from `MainAgent` where those orchestrators are already constructed (look for `DivideOrchestrator(` and `ParallelOrchestrator(` in `atria/core/agents/`). If not currently constructed there, leave `None` — the handler’s fallback path is already covered by tests.

- [ ] **Step 6: Commit**

```bash
git add atria/core/context_engineering/tools/registry_mixins/subagent_ops.py \
        tests/test_subagent_dispatch.py \
        atria/core/context_engineering/tools/*.py \
        atria/core/agents/main_agent/*.py
git commit -m "feat(dispatch): route spawn_subagent strategy=divide|parallel via DeLM orchestrators"
```

---

### Task 4: Web-server blackboard subscriber

**Files:**
- Create: `atria/web/blackboard_subscriber.py`
- Modify: `atria/web/server.py` (register lifecycle hook)
- Test: `tests/test_blackboard_subscriber.py` (new)

**Interfaces:**
- Consumes: Redis client (`redis.asyncio.Redis`), `ConnectionManager.broadcast(dict)`.
- Produces:
  - Background asyncio task subscribed to psub pattern `atria:bb:*:notes`.
  - For each received message, calls `broadcast({"type": "blackboard.note", "data": {"task_id", "thread_id", "type", "content", "ts"}})`.
  - Per-task throttle: at most 10 msgs/sec; overflow drops all but first and most recent within a 1s window, logs a WARNING once per burst.

- [ ] **Step 1: Write the failing test**

Create `tests/test_blackboard_subscriber.py`:
```python
"""Blackboard subscriber → WS broadcast."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from atria.web.blackboard_subscriber import BlackboardSubscriber


class FakePubSub:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)

    async def psubscribe(self, pattern: str) -> None:  # noqa: ARG002
        return None

    async def punsubscribe(self, pattern: str) -> None:  # noqa: ARG002
        return None

    async def get_message(
        self, ignore_subscribe_messages: bool = True, timeout: float = 1.0
    ) -> dict | None:
        if self._messages:
            return self._messages.pop(0)
        return None

    async def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> FakePubSub:
        return self._pubsub


class FakeBroadcaster:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.messages.append(message)


def _msg(task_id: str, thread_id: int, content: str) -> dict:
    payload = {
        "task_id": task_id,
        "thread_id": thread_id,
        "type": "fact",
        "content": content,
        "ts": 1.0,
    }
    return {
        "type": "pmessage",
        "pattern": b"atria:bb:*:notes",
        "channel": f"atria:bb:{task_id}:notes".encode(),
        "data": json.dumps(payload).encode(),
    }


@pytest.mark.asyncio
async def test_forwards_message_as_blackboard_note_event() -> None:
    pubsub = FakePubSub([_msg("bb_1", 0, "hello")])
    redis = FakeRedis(pubsub)
    bcast = FakeBroadcaster()

    sub = BlackboardSubscriber(redis, bcast)
    task = asyncio.create_task(sub.run(iterations=1))
    await task

    assert len(bcast.messages) == 1
    msg = bcast.messages[0]
    assert msg["type"] == "blackboard.note"
    assert msg["data"]["task_id"] == "bb_1"
    assert msg["data"]["content"] == "hello"


@pytest.mark.asyncio
async def test_throttle_drops_middle_of_burst() -> None:
    burst = [_msg("bb_2", 0, f"n{i}") for i in range(30)]
    pubsub = FakePubSub(burst)
    bcast = FakeBroadcaster()

    sub = BlackboardSubscriber(FakeRedis(pubsub), bcast, max_per_second=10)
    await sub.run(iterations=len(burst))

    # first + up to (max_per_second - 1) more per second window; strictly less than input.
    assert 1 <= len(bcast.messages) <= 10
    assert bcast.messages[0]["data"]["content"] == "n0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_blackboard_subscriber.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the subscriber**

Create `atria/web/blackboard_subscriber.py`:
```python
"""Redis pub/sub → WebSocket bridge for blackboard notes."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

_log = logging.getLogger(__name__)

_PATTERN = "atria:bb:*:notes"


class _Broadcaster(Protocol):
    async def broadcast(self, message: dict[str, Any]) -> None: ...


class BlackboardSubscriber:
    """Subscribe to blackboard note publishes and forward them to the WS layer.

    Per-task throttle: at most `max_per_second` notes per task_id per one-second
    window; excess notes are dropped and a single WARNING is logged per burst.
    """

    def __init__(
        self,
        redis: Any,
        broadcaster: _Broadcaster,
        *,
        max_per_second: int = 10,
    ) -> None:
        self._redis = redis
        self._broadcaster = broadcaster
        self._max = max_per_second
        self._buckets: dict[str, tuple[float, int, bool]] = {}
        self._stopped = False

    async def run(self, iterations: int | None = None) -> None:
        """Main loop. If `iterations` is set, stop after that many `get_message` calls."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(_PATTERN)
        try:
            seen = 0
            while not self._stopped:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if iterations is not None:
                    seen += 1
                    if seen >= iterations:
                        self._stopped = True
                if msg is None:
                    continue
                await self._forward(msg)
        finally:
            try:
                await pubsub.punsubscribe(_PATTERN)
                await pubsub.close()
            except Exception:  # noqa: BLE001 — best-effort shutdown
                pass

    def stop(self) -> None:
        self._stopped = True

    async def _forward(self, msg: dict[str, Any]) -> None:
        try:
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                data = data.decode()
            payload = json.loads(data)
        except Exception as exc:  # noqa: BLE001
            _log.warning("blackboard subscriber: bad payload: %s", exc)
            return

        task_id = payload.get("task_id") or ""
        if not self._admit(task_id):
            return

        await self._broadcaster.broadcast(
            {"type": "blackboard.note", "data": payload}
        )

    def _admit(self, task_id: str) -> bool:
        now = time.monotonic()
        bucket = self._buckets.get(task_id)
        if bucket is None or now - bucket[0] >= 1.0:
            self._buckets[task_id] = (now, 1, False)
            return True
        started, count, warned = bucket
        if count < self._max:
            self._buckets[task_id] = (started, count + 1, warned)
            return True
        if not warned:
            _log.warning(
                "blackboard subscriber: dropping notes for %s (>%d/s)",
                task_id,
                self._max,
            )
            self._buckets[task_id] = (started, count, True)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_blackboard_subscriber.py -v`
Expected: PASS — both cases green.

- [ ] **Step 5: Register lifecycle in the web server**

Find where the FastAPI app is created:
```bash
grep -n "FastAPI(\|@app.on_event\|lifespan" atria/web/server.py
```
Inside the existing startup path (either `lifespan` context or `@app.on_event("startup")`), add:
```python
        from redis.asyncio import Redis as AsyncRedis
        from atria.web.blackboard_subscriber import BlackboardSubscriber
        from atria.web.websocket import connection_manager  # existing singleton

        app.state.bb_redis = AsyncRedis.from_url(
            settings.redis_url  # reuse the same URL the rest of atria uses
        )
        app.state.bb_subscriber = BlackboardSubscriber(
            app.state.bb_redis, connection_manager
        )
        app.state.bb_subscriber_task = asyncio.create_task(
            app.state.bb_subscriber.run()
        )
```
And in the shutdown path:
```python
        try:
            app.state.bb_subscriber.stop()
            await asyncio.wait_for(app.state.bb_subscriber_task, timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            await app.state.bb_redis.aclose()
        except Exception:  # noqa: BLE001
            pass
```
(Adjust the singleton import name if the existing broadcaster is exposed under a different symbol — grep in `websocket.py` for the exported instance.)

- [ ] **Step 6: Commit**

```bash
git add atria/web/blackboard_subscriber.py atria/web/server.py \
        tests/test_blackboard_subscriber.py
git commit -m "feat(web): blackboard subscriber bridges redis pub/sub → WebSocket"
```

---

### Task 5: Frontend store — notes field + WS handler

**Files:**
- Modify: `web-ui/src/stores/solverJobs.ts`
- Modify: `web-ui/src/types/*.ts` (WS event type — grep to locate)
- Test: `web-ui/src/stores/solverJobs.test.ts` (new)

**Interfaces:**
- Consumes: WebSocket message `{type: "blackboard.note", data: {task_id, thread_id, type, content, ts}}`.
- Produces:
  - Store gains `notes: BBNote[]` on `DivideTaskView` and `ThreadState`.
  - `BBNote = { type: string; content: string; ts: number; thread_id: number }`.
  - Notes capped at 50 per task/thread (drop oldest).
  - Divide task lookup: task whose `id` equals `t{thread_id}` OR whose task index matches `thread_id`. Parallel thread lookup: `thread === thread_id`.

- [ ] **Step 1: Write the failing test**

Create `web-ui/src/stores/solverJobs.test.ts`:
```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useSolverJobsStore } from './solverJobs';

function seedDivide() {
  useSolverJobsStore.setState({
    jobs: {
      job_a: {
        strategy: 'divide',
        jobId: 'job_a',
        module: 'm',
        request: 'r',
        tasks: [
          { id: 't0', description: 'x', depends_on: [], status: 'running', notes: [] },
        ],
        status: 'running',
        startedAt: 1,
        updatedAt: 1,
      },
    },
    order: ['job_a'],
  });
}

describe('solverJobs blackboard.note', () => {
  beforeEach(() => {
    useSolverJobsStore.getState().clear();
  });

  it('appends a note to a matching divide task', () => {
    seedDivide();
    useSolverJobsStore.getState().onBlackboardNote({
      task_id: 'dw_job_a',
      thread_id: 0,
      type: 'fact',
      content: 'hi',
      ts: 1,
    }, 'job_a');
    const job = useSolverJobsStore.getState().jobs.job_a as any;
    expect(job.tasks[0].notes.length).toBe(1);
    expect(job.tasks[0].notes[0].content).toBe('hi');
  });

  it('caps notes at 50, dropping oldest', () => {
    seedDivide();
    for (let i = 0; i < 60; i++) {
      useSolverJobsStore.getState().onBlackboardNote({
        task_id: 'dw_job_a',
        thread_id: 0,
        type: 'fact',
        content: `n${i}`,
        ts: i,
      }, 'job_a');
    }
    const job = useSolverJobsStore.getState().jobs.job_a as any;
    expect(job.tasks[0].notes.length).toBe(50);
    expect(job.tasks[0].notes[0].content).toBe('n10');
    expect(job.tasks[0].notes[49].content).toBe('n59');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web-ui && npx vitest run src/stores/solverJobs.test.ts`
Expected: FAIL — `onBlackboardNote` not defined; `notes` field missing.

- [ ] **Step 3: Extend types and store**

In `web-ui/src/stores/solverJobs.ts`:
- Add near the top of the file:
  ```ts
  export interface BBNote {
    type: string;
    content: string;
    ts: number;
    thread_id: number;
  }
  const MAX_NOTES = 50;
  ```
- Extend `DivideTaskView`:
  ```ts
  export interface DivideTaskView {
    id: string;
    description: string;
    depends_on: string[];
    status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
    result?: string;
    notes: BBNote[];
  }
  ```
- Extend `ThreadState`:
  ```ts
  export interface ThreadState {
    thread: number;
    status: 'running' | 'done' | 'dropped';
    ok?: boolean;
    summary?: string;
    winner?: boolean;
    notes: BBNote[];
  }
  ```
- Wherever tasks/threads are seeded from WS events (the existing dispatch job register handlers), initialize `notes: []`.
- Add the store action:
  ```ts
  onBlackboardNote: (
    payload: {
      task_id: string;
      thread_id: number;
      type: string;
      content: string;
      ts: number;
    },
    hintedJobId?: string,
  ) => {
    set((state) => {
      // Resolve job. Preferred: hintedJobId (test path); real path uses the
      // reverse map (bb_id → jobId) maintained on dispatch.job_register.
      const jobId =
        hintedJobId ??
        state.bbToJob[payload.task_id];
      if (!jobId) return {};
      const job = state.jobs[jobId];
      if (!job) return {};

      const note: BBNote = {
        type: payload.type,
        content: payload.content,
        ts: payload.ts,
        thread_id: payload.thread_id,
      };

      if (job.strategy === 'divide') {
        const idx = job.tasks.findIndex(
          (t) => t.id === `t${payload.thread_id}`,
        );
        if (idx < 0) return {};
        const tasks = [...job.tasks];
        const existing = tasks[idx].notes ?? [];
        const merged = [...existing, note];
        if (merged.length > MAX_NOTES) merged.splice(0, merged.length - MAX_NOTES);
        tasks[idx] = { ...tasks[idx], notes: merged };
        return {
          jobs: { ...state.jobs, [jobId]: { ...job, tasks, updatedAt: Date.now() } },
        };
      }
      // parallel
      const idx = job.threads.findIndex((t) => t.thread === payload.thread_id);
      if (idx < 0) return {};
      const threads = [...job.threads];
      const existing = threads[idx].notes ?? [];
      const merged = [...existing, note];
      if (merged.length > MAX_NOTES) merged.splice(0, merged.length - MAX_NOTES);
      threads[idx] = { ...threads[idx], notes: merged };
      return {
        jobs: { ...state.jobs, [jobId]: { ...job, threads, updatedAt: Date.now() } },
      };
    });
  },
  ```
- Add a `bbToJob: Record<string, string>` to the store state and populate it whenever the dispatch job register handler runs (both divide and parallel paths). Values: `payload.blackboard_task_id → jobId`. Remove entries on `job done/failed` events.

- In the WS message dispatcher for this store (grep the file for the existing `switch` on `type`), add a case:
  ```ts
  case 'blackboard.note':
    useSolverJobsStore.getState().onBlackboardNote(msg.data);
    break;
  ```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web-ui && npx vitest run src/stores/solverJobs.test.ts`
Expected: PASS — both cases green.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/stores/solverJobs.ts web-ui/src/stores/solverJobs.test.ts
git commit -m "feat(web-ui): blackboard notes on solverJobs store"
```

---

### Task 6: DispatchPage — inline notes rendering

**Files:**
- Modify: `web-ui/src/pages/DispatchPage.tsx`

**Interfaces:**
- Consumes: `notes: BBNote[]` field added in Task 5.
- Produces:
  - `TaskRow` and `ThreadRow` render a collapsible notes block below existing content.
  - Default collapsed when `> 3 notes`, showing last 3 with a `… N more` toggle.
  - Each note: one-line `[type-badge] content` (truncate + full-content tooltip).
  - Type → color:
    - `fact` → `text-slate-300`
    - `question` → `text-amber-400`
    - `decision` → `text-emerald-400`
    - `blocker` → `text-semantic-danger`
    - other → `text-text-400`
  - New note pulse: 200ms fade highlight, gated on `prefers-reduced-motion`.
  - Hide block entirely if `notes.length === 0 && status === 'pending'`.

- [ ] **Step 1: Add the `NotesStream` component**

Insert above `TaskRow` in `web-ui/src/pages/DispatchPage.tsx`:
```tsx
import { useState, useEffect, useRef } from 'react';
import type { BBNote } from '../stores/solverJobs';

const NOTE_COLOR: Record<string, string> = {
  fact: 'text-slate-300',
  question: 'text-amber-400',
  decision: 'text-emerald-400',
  blocker: 'text-semantic-danger',
};

function NoteLine({ note, pulse }: { note: BBNote; pulse: boolean }) {
  const color = NOTE_COLOR[note.type] ?? 'text-text-400';
  return (
    <div
      className={`text-[11px] font-mono truncate ${color} ${pulse ? 'animate-note-pulse motion-reduce:animate-none' : ''}`}
      title={`${note.type}: ${note.content}`}
    >
      <span className="opacity-60 mr-1">[{note.type}]</span>
      {note.content}
    </div>
  );
}

function NotesStream({
  notes,
  hiddenWhenPending,
  status,
}: {
  notes: BBNote[];
  hiddenWhenPending?: boolean;
  status?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const prev = useRef(notes.length);
  const isNew = notes.length > prev.current;
  useEffect(() => {
    prev.current = notes.length;
  }, [notes.length]);

  if (notes.length === 0 && (hiddenWhenPending || status === 'pending')) return null;
  if (notes.length === 0) return null;

  const visible = expanded ? notes : notes.slice(-3);
  const hidden = notes.length - visible.length;
  return (
    <div className="ml-16 mr-4 pb-2 space-y-0.5">
      {visible.map((n, i) => (
        <NoteLine
          key={`${n.ts}-${i}`}
          note={n}
          pulse={isNew && i === visible.length - 1}
        />
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-[10px] font-mono text-text-500 hover:text-text-300 transition-colors"
          aria-label={`Show ${hidden} more notes`}
        >
          … {hidden} more
        </button>
      )}
      {expanded && notes.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="text-[10px] font-mono text-text-500 hover:text-text-300 transition-colors"
        >
          collapse
        </button>
      )}
    </div>
  );
}
```

Add to `web-ui/src/index.css` (or the design-tokens layer used by the project — grep for `animate-pulse-dot` to find the right file):
```css
@keyframes note-pulse {
  0% { background-color: rgba(255, 191, 0, 0.20); }
  100% { background-color: transparent; }
}
.animate-note-pulse { animation: note-pulse 200ms ease-out; }
```

- [ ] **Step 2: Render notes under TaskRow**

Replace the `<div>` returned by `TaskRow` with:
```tsx
  return (
    <>
      <div className="flex items-start gap-3 px-4 py-2 border-t border-border-300/10 transition-colors duration-150 hover:bg-bg-100/30">
        {/* …unchanged existing content… */}
      </div>
      <NotesStream notes={task.notes ?? []} status={task.status} />
    </>
  );
```

- [ ] **Step 3: Render notes under ThreadRow**

Replace the returned `<div>` of `ThreadRow` with:
```tsx
  return (
    <>
      <div className="flex items-start gap-3 px-4 py-2 border-t border-border-300/10 transition-colors hover:bg-bg-100/30">
        {/* …unchanged existing content… */}
      </div>
      <NotesStream notes={thread.notes ?? []} />
    </>
  );
```

- [ ] **Step 4: Build the UI**

Run: `make build-ui`
Expected: build succeeds; `atria/web/static/` regenerated.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/pages/DispatchPage.tsx web-ui/src/index.css atria/web/static
git commit -m "feat(web-ui): inline blackboard notes stream on Dispatch page"
```

---

### Task 7: System-prompt strategy guidance

**Files:**
- Modify: one file under `atria/core/agents/prompts/templates/system/main/` (grep for the section that currently documents `spawn_subagent`).

**Interfaces:**
- Consumes: existing PromptComposer section registration.
- Produces: an inline paragraph explaining when the LLM should choose `direct`, `divide`, or `parallel`. Plain prose + bullets, no tables (project CLAUDE.md rule).

- [ ] **Step 1: Locate the section that documents spawn_subagent**

Run:
```bash
grep -rn "spawn_subagent" atria/core/agents/prompts/templates/system/main/
```
Pick the file that already describes the tool (create a new section only if none exists).

- [ ] **Step 2: Add the guidance paragraph**

Append (do not replace existing content):
```markdown
### Choosing a spawn_subagent strategy

Every `spawn_subagent` call now takes an optional `strategy` field. Default is
`direct`, which runs one subagent through the existing SubAgentManager — pick
this for a single, focused delegation to a specialized agent type.

Use `divide` when the work is a multi-step problem whose subtasks depend on
each other. The prompt is decomposed into a small DAG and executed as one
unit. Set `subagent_type` as a hint about which module/skill to bias
decomposition toward.

Use `parallel` when the task is a single well-scoped problem and racing a few
candidate approaches is worth the overhead. N solvers work in isolated
worktrees; the judge picks and applies a winner. Keep the prompt tight — the
solvers will diverge if the instructions are loose.

If `divide` or `parallel` returns an error mentioning the orchestrator is not
configured (Redis or Docker unavailable), fall back to `direct`.
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/agents/prompts/templates/system/main/
git commit -m "docs(prompt): teach LLM when to use divide vs parallel vs direct"
```

---

### Task 8: End-to-end verification

**Files:** (no source edits; verification only.)

**Interfaces:** Uses the running `atria run ui` process + a real `OPENAI_API_KEY` per project CLAUDE.md.

- [ ] **Step 1: Preconditions**

```bash
export OPENAI_API_KEY="…"
# Confirm redis + docker are up:
docker ps | head
redis-cli ping   # should print PONG
```

- [ ] **Step 2: Unit tests all green**

Run:
```bash
make test
```
Expected: all tests from Tasks 1–5 green (plus existing suite).

- [ ] **Step 3: Launch web UI**

Run:
```bash
make run
# or: atria run ui
```
Open the browser tab; navigate to Dispatch.

- [ ] **Step 4: strategy=parallel end-to-end**

Send a chat prompt: `Race 3 solvers to add a docstring to atria/core/blackboard/store.py`.

Expected:
- New parallel job appears on Dispatch page.
- Under each thread row, notes begin streaming (type badges + content).
- Latest note briefly flashes on arrival.
- Job settles to `Applied` or `Not applied`; conflicted files list matches server logs.

- [ ] **Step 5: strategy=divide end-to-end**

Send: `Decompose and execute: plan a 3-step refactor of atria/core/blackboard/render.py.`

Expected:
- New divide job appears with 2–3 DAG tasks.
- Each task row streams notes as the module_worker runs.
- Job completes with a summary line.

- [ ] **Step 6: Fallback path**

Stop redis (`brew services stop redis` or equivalent). Send a divide-strategy prompt.

Expected:
- Tool returns an error telling the LLM to retry with `strategy="direct"`; the LLM does so and completes the task.

- [ ] **Step 7: Commit the verification log**

Write a short markdown summary of what you observed in each step to
`docs/superpowers/verification/2026-07-01-dispatch-blackboard-ui.md` and commit:
```bash
git add -f docs/superpowers/verification/2026-07-01-dispatch-blackboard-ui.md
git commit -m "chore(verification): dispatch + blackboard UI E2E notes"
```

---

## Self-review checklist for the implementer

- [ ] Every `- [ ]` step in Tasks 1–8 is checked.
- [ ] `spawn_subagent` still behaves identically when `strategy` is unset.
- [ ] `BlackboardStore.append` never raises on publish failure (Task 1 test covers this).
- [ ] Notes cap at 50 per task/thread; oldest dropped first (Task 5 test covers this).
- [ ] Type badges use the color mapping from Task 6 verbatim.
- [ ] No tables were introduced into any system prompt (Task 7).
