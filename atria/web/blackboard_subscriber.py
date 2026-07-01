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

    Args:
        redis: An async Redis client (or compatible object exposing `pubsub()`).
        broadcaster: Object with an async `broadcast(dict)` method (e.g. ws_manager).
        max_per_second: Maximum messages forwarded per task_id per second.
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
        # Per task_id: (window_start, count_in_window, warned_this_burst)
        self._buckets: dict[str, tuple[float, int, bool]] = {}
        self._stopped = False

    async def run(self, iterations: int | None = None) -> None:
        """Main subscription loop.

        Args:
            iterations: If set, stop after this many `get_message` calls (for testing).
        """
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
        """Signal the run loop to exit on its next iteration."""
        self._stopped = True

    async def _forward(self, msg: dict[str, Any]) -> None:
        """Decode a raw pub/sub message and broadcast it if within throttle limits.

        Args:
            msg: Raw message dict from redis pubsub.get_message().
        """
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
        """Apply per-task rate limit; return True if message should be forwarded.

        Args:
            task_id: The task identifier from the payload.

        Returns:
            True if the message is within quota, False if it should be dropped.
        """
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
