"""Lightweight Redis-backed bookkeeping for in-flight task IDs.

Used to distinguish "still running" from "orphaned" (worker died) on the
collect side, and to let the scheduler janitor reap stale entries. Keys are
small and carry their own TTL so they self-clean even if the janitor lags.

Under ENVIRONMENT=pytest all operations are no-ops so tests need no Redis.
"""
from __future__ import annotations

import os
import time

import redis.asyncio as aioredis

_PREFIX = "atria:task:meta:"
_META_TTL = 24 * 3600  # seconds; janitor normally removes earlier


def _is_pytest() -> bool:
    return os.environ.get("ENVIRONMENT") == "pytest"


async def record_enqueue(redis_url: str, task_id: str, session_id: str) -> None:
    if _is_pytest():
        return
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
    if _is_pytest():
        return None
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
    if _is_pytest():
        return []
    r = aioredis.from_url(redis_url)
    reaped: list[str] = []
    try:
        async for key in r.scan_iter(match=_PREFIX + "*"):
            created = await r.hget(key, "created_at")
            if created is not None and (time.time() - float(created)) > max_age:
                await r.delete(key)
                k = key.decode() if isinstance(key, bytes) else key
                reaped.append(k[len(_PREFIX) :])
    finally:
        await r.aclose()
    return reaped
