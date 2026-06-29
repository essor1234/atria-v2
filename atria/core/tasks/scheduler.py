"""TaskIQ scheduler + orphan-reaping janitor.

Run with:
    taskiq scheduler atria.core.tasks.scheduler:scheduler
"""
from __future__ import annotations

import logging
import os

import redis.asyncio as aioredis
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from atria.core.tasks import meta
from atria.core.tasks.broker import broker

logger = logging.getLogger(__name__)


def _janitor_redis_url() -> str:
    return os.environ.get("ATRIA_REDIS_URL", "redis://localhost:6379/0")


def _orphan_after() -> int:
    return int(os.environ.get("ATRIA_TASK_ORPHAN_AFTER", "1800"))


@broker.task(
    task_name="atria.core.tasks.scheduler.reap_orphan_tasks",
    schedule=[{"cron": "*/10 * * * *"}],
)
async def reap_orphan_tasks() -> int:
    """Delete meta entries for tasks past the orphan age. Returns the count reaped."""
    redis = aioredis.from_url(_janitor_redis_url())
    try:
        reaped = await meta.reap_orphans(redis, max_age=_orphan_after())
    finally:
        await redis.aclose()
    if reaped:
        logger.warning("reaped %d orphaned task(s): %s", len(reaped), reaped)
    return len(reaped)


scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
