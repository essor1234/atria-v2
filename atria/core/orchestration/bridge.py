"""Sync→async bridge shared by orchestrators driven from the loopless agent thread."""
from __future__ import annotations

import asyncio
from typing import Any, Callable


def make_run_async(task_client: Any) -> Callable[[Any], Any]:
    """Return ``run_async(coro)`` that runs a coroutine on the task client's loop.

    Ensures the task client's persistent background loop is started, then submits
    coroutines to it via ``run_coroutine_threadsafe``. Reusing one loop keeps all of an
    orchestrator's async work (job store + blackboard) — and any redis client bound to
    it — consistent, rather than spinning up a second loop.
    """
    task_client.startup()

    def run_async(coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, task_client._loop).result()

    return run_async


def ensure_async_redis(redis_client: Any, url: str) -> Any:
    """Return ``redis_client`` if given, else build an async redis client from ``url``."""
    if redis_client is not None:
        return redis_client
    import redis.asyncio as aioredis

    return aioredis.from_url(url)
