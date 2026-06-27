"""Blackboard facade (async) + synchronous handle (background-loop bridge)."""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable

from atria.core.blackboard.archive import archive_to_postgres
from atria.core.blackboard.models import Note
from atria.core.blackboard.render import render_digest
from atria.core.blackboard.verifier import verify_notes

logger = logging.getLogger(__name__)


class Blackboard:
    """Compose verifier + store + render + archive for one task."""

    def __init__(
        self,
        store: Any,
        *,
        thread_id: int = 0,
        window_tokens: int = 2000,
        session_factory: Callable[[], object] | None = None,
        owner_id: str = "",
    ) -> None:
        self._store = store
        self._thread_id = thread_id
        self._window_tokens = window_tokens
        self._session_factory = session_factory
        self._owner_id = owner_id
        self._task_id = getattr(store, "_key", "atria:bb:?").removeprefix("atria:bb:")

    async def write(self, raw_notes: list[dict]) -> str:
        """Verify then append notes. Returns the verifier status, or a soft-failure string."""
        try:
            clean, status = verify_notes(raw_notes)
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

    async def archive(self) -> int:
        """Flush the final blackboard to Postgres (best-effort)."""
        if self._session_factory is None:
            return 0
        try:
            notes = await self._store.read_all()
            return await archive_to_postgres(
                self._session_factory, self._task_id, self._owner_id, notes
            )
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _now() -> float:
        return time.time()


class BlackboardHandle:
    """Synchronous proxy over Blackboard for the (loopless) agent thread.

    Owns one persistent daemon-thread event loop, same shape as
    atria.core.tasks.client.TaskIQClient.
    """

    def __init__(self, blackboard: Blackboard, redis_client: Any = None) -> None:
        self._bb = blackboard
        self._redis_client = redis_client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False

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
        self.startup()
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

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

    def archive(self) -> int:
        """Archive to Postgres synchronously; returns 0 on any error."""
        try:
            return self._submit(self._bb.archive())
        except Exception:  # noqa: BLE001
            return 0
