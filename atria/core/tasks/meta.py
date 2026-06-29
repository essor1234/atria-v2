"""Lightweight Redis-backed bookkeeping for in-flight task IDs.

Used to distinguish "still running" from "orphaned" (worker died) on the
collect side, and to let the scheduler janitor reap stale entries. Keys are
small and carry their own TTL so they self-clean even if the janitor lags.

The caller owns the redis client lifecycle (create, pass in, close). These
functions never open or close connections themselves.
"""
from __future__ import annotations

import time

_PREFIX = "atria:task:meta:"
_META_TTL = 24 * 3600  # seconds; janitor normally removes earlier


async def record_enqueue(redis: object, task_id: str, session_id: str) -> None:
    """Record that *task_id* has been enqueued for *session_id*.

    Args:
        redis: An async redis client (caller-owned lifecycle).
        task_id: The TaskIQ task ID returned by kiq().
        session_id: The Atria session that owns this task.
    """
    await redis.hset(  # type: ignore[attr-defined]
        _PREFIX + task_id,
        mapping={"created_at": str(time.time()), "session_id": session_id},
    )
    await redis.expire(_PREFIX + task_id, _META_TTL)  # type: ignore[attr-defined]


async def age_seconds(redis: object, task_id: str) -> float | None:
    """Return how many seconds ago *task_id* was enqueued, or None if unknown.

    Args:
        redis: An async redis client (caller-owned lifecycle).
        task_id: The TaskIQ task ID to look up.

    Returns:
        Elapsed seconds since enqueue, or None if no meta entry exists.
    """
    created = await redis.hget(_PREFIX + task_id, "created_at")  # type: ignore[attr-defined]
    if created is None:
        return None
    return time.time() - float(created)


async def reap_orphans(redis: object, max_age: float) -> list[str]:
    """Delete meta entries older than *max_age*. Returns the reaped task_ids.

    Args:
        redis: An async redis client (caller-owned lifecycle).
        max_age: Maximum age in seconds before a task is considered orphaned.

    Returns:
        List of task_id strings whose meta entries were deleted.
    """
    reaped: list[str] = []
    async for key in redis.scan_iter(match=_PREFIX + "*"):  # type: ignore[attr-defined]
        created = await redis.hget(key, "created_at")  # type: ignore[attr-defined]
        if created is not None and (time.time() - float(created)) > max_age:
            await redis.delete(key)  # type: ignore[attr-defined]
            k = key.decode() if isinstance(key, bytes) else key
            reaped.append(k[len(_PREFIX) :])
    return reaped
