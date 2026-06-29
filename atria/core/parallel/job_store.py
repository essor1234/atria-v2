"""Redis-backed record for an in-flight parallel-solve job. Caller owns the redis client."""
from __future__ import annotations

import json

_PREFIX = "atria:pjob:"


class JobStore:
    """CRUD for parallel-solve job records keyed atria:pjob:{job_id}."""

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
