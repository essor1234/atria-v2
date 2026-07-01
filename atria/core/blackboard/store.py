"""Redis hot-path store for a task's blackboard notes.

The caller owns the redis client lifecycle (create, pass in, close). This class
never opens or closes connections — mirrors atria/core/tasks/meta.py.
"""
from __future__ import annotations

import json
import logging

from atria.core.blackboard.models import Note

_PREFIX = "atria:bb:"
_log = logging.getLogger(__name__)


class BlackboardStore:
    """Append-only note list for one task, keyed atria:bb:{task_id}."""

    def __init__(self, redis: object, task_id: str, ttl: int) -> None:
        self._redis = redis
        self._key = _PREFIX + task_id
        self._ttl = ttl

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

    async def read_all(self) -> list[Note]:
        """Return all notes in insertion order."""
        raw = await self._redis.lrange(self._key, 0, -1)  # type: ignore[attr-defined]
        out: list[Note] = []
        for item in raw or []:
            s = item.decode() if isinstance(item, bytes) else item
            out.append(Note.from_dict(json.loads(s)))
        return out
