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
    return ListQueueBroker(url=redis_url).with_result_backend(result_backend)


# Process-global singleton imported by the worker/scheduler CLIs and the server
# lifespan. The broker's queue and result backend are fixed to the default Redis
# URL at import time and are NOT reconfigured from AppConfig.tasks.redis_url
# (that URL currently only configures a separate orphan meta-store). All
# processes must share the same default URL for the broker to function.
broker: AsyncBroker = make_broker("redis://localhost:6379/0", result_ttl=3600)
