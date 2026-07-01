"""Redis-backed CRUD for in-flight orchestration job records. Caller owns the redis client.

One implementation shared by the parallel-solve and divide-work orchestrators; the
``prefix`` namespaces the two job kinds in the same Redis instance.
"""
from __future__ import annotations

import json

# Key prefixes for the two job kinds (kept stable for compatibility with live jobs).
PARALLEL_PREFIX = "atria:pjob:"
DIVIDE_PREFIX = "atria:dw:"


class JobStore:
    """CRUD for job records keyed ``{prefix}{job_id}``."""

    def __init__(self, redis: object, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def save(self, job_id: str, record: dict, ttl: int) -> None:
        await self._redis.set(  # type: ignore[attr-defined]
            self._prefix + job_id, json.dumps(record), ex=ttl
        )

    async def load(self, job_id: str) -> dict | None:
        raw = await self._redis.get(self._prefix + job_id)  # type: ignore[attr-defined]
        if raw is None:
            return None
        s = raw.decode() if isinstance(raw, bytes) else raw
        return json.loads(s)

    async def delete(self, job_id: str) -> None:
        await self._redis.delete(self._prefix + job_id)  # type: ignore[attr-defined]
