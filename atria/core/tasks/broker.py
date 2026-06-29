"""TaskIQ broker factory and process-global broker singleton.

Mirrors atria.web.bus.make_bus: one factory, one module-level singleton that
the `taskiq worker` / `taskiq scheduler` CLIs import. ListQueueBroker is used
(at-most-once, no acknowledgements) so a crashed worker never silently
re-runs a side-effecting subagent.
"""
from __future__ import annotations

import os

from taskiq import AsyncBroker, InMemoryBroker
from taskiq_redis import ListQueueBroker, RedisAsyncResultBackend


def make_broker(redis_url: str, result_ttl: int) -> AsyncBroker:
    """Return the broker for the current environment.

    Under ENVIRONMENT=pytest, returns an in-process broker so unit tests need
    no Redis. Otherwise a Redis ListQueueBroker with a Redis result backend.
    """
    if os.environ.get("ENVIRONMENT") == "pytest":
        return InMemoryBroker(await_inplace=True)
    result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
        redis_url=redis_url,
        result_ex_time=result_ttl,
    )
    # socket_timeout=None on the broker connection: the worker's listen loop does
    # a blocking BRPOP that waits indefinitely for tasks. redis-py defaults
    # socket_timeout to 5s, which would fire mid-BRPOP and raise
    # redis.TimeoutError — and taskiq-redis's listen() only catches
    # ConnectionError, so that timeout crashes the worker. None lets BRPOP block.
    # (socket_connect_timeout keeps its own 5s default, so connects still fail fast.)
    return ListQueueBroker(url=redis_url, socket_timeout=None).with_result_backend(
        result_backend
    )


# Process-global singleton imported by the worker/scheduler CLIs and the server
# lifespan. The broker URL is fixed at import time (before AppConfig loads), so
# it reads the ``ATRIA_REDIS_URL`` env var — every process (server + worker +
# scheduler) must share the same value for the broker to function. Defaults to
# localhost for local/dev; in Docker set ATRIA_REDIS_URL=redis://redis:6379/0.
broker: AsyncBroker = make_broker(
    os.environ.get("ATRIA_REDIS_URL", "redis://localhost:6379/0"), result_ttl=3600
)
