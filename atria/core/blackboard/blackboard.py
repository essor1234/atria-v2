"""Blackboard facade (async) + synchronous handle (background-loop bridge)."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable

from atria.core.blackboard.admission import admit_notes
from atria.core.blackboard.models import Note
from atria.core.blackboard.render import render_digest
from atria.core.blackboard.verifier import verify_notes

logger = logging.getLogger(__name__)


class Blackboard:
    """Compose verifier + store + render for one task's shared context."""

    def __init__(
        self,
        store: Any,
        *,
        thread_id: int = 0,
        window_tokens: int = 2000,
        owner_id: str = "",
        verify_llm: Callable[[str, str], str] | None = None,
    ) -> None:
        self._store = store
        self._thread_id = thread_id
        self._window_tokens = window_tokens
        self._owner_id = owner_id  # run/owner identity (telemetry); not persisted
        self._verify_llm = verify_llm
        self._task_id = getattr(store, "_key", "atria:bb:?").removeprefix("atria:bb:")

    async def write(self, raw_notes: list[dict]) -> str:
        """Hygiene-check, LLM-verify, then append notes.

        Two gates run in order: deterministic hygiene (``verify_notes``) and, when a
        verifier model is wired, admission-time LLM verification (``admit_notes``,
        DeLM §A.3) that rejects ungrounded/speculative claims. Returns a status string
        (e.g. ``"ok:2/3,rejected=1"``), or a soft-failure string on error.
        """
        try:
            clean, status = verify_notes(raw_notes)
            if not clean:
                return status
            if self._verify_llm is not None:
                admitted, reasons = await admit_notes(clean, self._verify_llm)
                if reasons:
                    status += f",rejected={len(reasons)}"
                    for reason in reasons:
                        logger.info("blackboard admission rejected — %s", reason)
                clean = admitted
                if not clean:
                    return status
            now = self._now()
            await self._store.append(
                [Note(type=c["type"], content=c["content"], thread_id=self._thread_id, ts=now)
                 for c in clean]
            )
        except Exception as exc:  # noqa: BLE001 — accelerant, never hard-fail
            logger.warning("blackboard write failed: %s", exc)
            return "blackboard unavailable"
        return status

    async def render(self, viewer_id: int | None = None) -> str:
        """Render the current digest, or "" on any failure."""
        try:
            notes = await self._store.read_all()
            vid = self._thread_id if viewer_id is None else viewer_id
            return render_digest(notes, viewer_id=vid, window_tokens=self._window_tokens)
        except Exception as exc:  # noqa: BLE001
            logger.warning("blackboard render failed: %s", exc)
            return ""

    @staticmethod
    def _now() -> float:
        return time.time()


class BlackboardHandle:
    """Synchronous proxy over Blackboard for the (loopless) agent thread.

    The bridge is load-bearing, not incidental: the blackboard store is async
    (``redis.asyncio``), but its only callers are synchronous — the NOTE tool
    (``note_tool.py``, ``blackboard.write``) and prompt assembly
    (``injection.py``, ``blackboard.render``) both run on the agent's loopless
    tool-execution thread. This handle owns one persistent daemon-thread event
    loop (same shape as ``atria.core.tasks.client.TaskIQClient``) so those sync
    callers can drive the async store without each spinning up its own loop.
    """

    def __init__(self, blackboard: Blackboard, redis_client: Any = None) -> None:
        self._bb = blackboard
        self._redis_client = redis_client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False
        # Maximum seconds to wait for any single async op via _submit.
        # concurrent.futures.TimeoutError is an Exception subclass, so the
        # existing try/except blocks in write/render/archive degrade gracefully.
        self._op_timeout: float = 15.0

    def startup(self) -> None:
        """Start the background event loop thread."""
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._started = True

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        """Stop the background event loop thread."""
        with self._lock:
            if not self._started or self._loop is None:
                return
            if self._redis_client is not None:
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        self._redis_client.aclose(), self._loop
                    )
                    fut.result(timeout=5)
                except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                    logger.warning("blackboard redis close failed: %s", exc)
                self._redis_client = None
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._started = False
            self._loop = None

    def _submit(self, coro: Any) -> Any:
        import concurrent.futures

        self.startup()
        assert self._loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=self._op_timeout)
        except concurrent.futures.TimeoutError:
            # Cancel the underlying asyncio task and drain one event-loop tick so
            # the cancellation can propagate before the caller might shut down the
            # loop.  This prevents "Task was destroyed but pending/cancelling" asyncio
            # warnings when shutdown() is called shortly after a timed-out operation.
            fut.cancel()
            try:
                asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self._loop).result(
                    timeout=1.0
                )
            except Exception:  # noqa: BLE001 — best-effort drain
                pass
            raise

    def write(self, raw_notes: list[dict]) -> str:
        """Write notes synchronously; returns 'blackboard unavailable' on any error."""
        try:
            return self._submit(self._bb.write(raw_notes))
        except Exception as exc:  # noqa: BLE001
            logger.warning("blackboard handle write failed: %s", exc)
            return "blackboard unavailable"

    def render(self) -> str:
        """Render digest synchronously; returns '' on any error."""
        try:
            return self._submit(self._bb.render())
        except Exception:  # noqa: BLE001
            return ""
