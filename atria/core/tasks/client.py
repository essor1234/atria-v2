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

import redis.asyncio as aioredis
from taskiq import AsyncBroker
from taskiq_redis.exceptions import ResultIsMissingError

from atria.core.tasks import meta
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)

_TASK_NAME = "atria.core.tasks.tasks.run_background_subagent"


class TaskIQClient:
    """Enqueue background subagents and collect their results, synchronously."""

    def __init__(
        self,
        broker: AsyncBroker,
        redis_url: str,
        orphan_after: int = 1800,
        redis_client: Any = None,
    ):
        self._broker = broker
        self._redis_url = redis_url
        self._orphan_after = orphan_after
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        # Injected client is caller-owned; None means we create and own it.
        self._redis_client: Any = redis_client
        self._redis_client_owned = redis_client is None

    # ── loop lifecycle ───────────────────────────────────────────────────
    def startup(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            # If no client was injected, create one on the loop thread.
            if self._redis_client_owned:
                fut = asyncio.run_coroutine_threadsafe(
                    self._create_redis_client(), self._loop
                )
                self._redis_client = fut.result(timeout=10)
            self._submit(self._broker.startup())
            self._started = True

    async def _create_redis_client(self) -> Any:
        return aioredis.from_url(self._redis_url)

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        if not self._started or self._loop is None:
            return
        try:
            self._submit(self._broker.shutdown())
            if self._redis_client_owned and self._redis_client is not None:
                self._submit(self._redis_client.aclose())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
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
        await meta.record_enqueue(self._redis_client, kicked.task_id, payload.session_id)
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
        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
        while True:
            if await backend.is_result_ready(task_id):
                # Known limitation: when result TTL < orphan_after, a task whose
                # result has expired but whose meta entry still exists will be
                # reported as "running" until orphan_after, then "orphaned".
                # Acceptable for MVP — Task 8 must not assume otherwise.
                try:
                    res = await backend.get_result(task_id, with_logs=False)
                except ResultIsMissingError:
                    return {
                        "success": False,
                        "status": "expired",
                        "error": "result expired",
                    }
                if res.is_err:
                    return {
                        "success": False,
                        "status": "failed",
                        "error": str(res.error),
                    }
                value = res.return_value or {}
                return {**value, "success": value.get("success", True), "status": "done"}
            if not block or asyncio.get_running_loop().time() >= deadline:
                age = await meta.age_seconds(self._redis_client, task_id)
                if age is not None and age > self._orphan_after:
                    return {
                        "success": False,
                        "status": "failed",
                        "error": "orphaned",
                        "reason": "orphaned",
                    }
                return {"success": False, "status": "running"}
            await asyncio.sleep(0.25)
