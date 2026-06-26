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
