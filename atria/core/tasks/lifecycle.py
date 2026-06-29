"""Lifecycle helpers wiring the TaskIQ client into the web server.

The background-subagent task is registered on the module-singleton broker
(atria.core.tasks.broker.broker). Importing atria.core.tasks.tasks here ensures
the @broker.task decorator has run so the client can find it by name.
"""
from __future__ import annotations

import logging
from typing import Any

from atria.core.tasks import tasks as _tasks  # noqa: F401 — registers the task on the broker
from atria.core.tasks.broker import broker
from atria.core.tasks.client import TaskIQClient

logger = logging.getLogger(__name__)


def make_task_client(redis_url: str, orphan_after: int) -> TaskIQClient:
    """Build (do not start) a TaskIQClient bound to the singleton broker.

    Args:
        redis_url: Redis connection URL for result backend and meta store.
        orphan_after: Seconds after which an unfinished task is considered orphaned.

    Returns:
        An unstarted TaskIQClient bound to the module-singleton broker.
    """
    return TaskIQClient(broker, redis_url=redis_url, orphan_after=orphan_after)


def attach_task_client(tool_registry: Any, client: Any) -> None:
    """Attach the task client to a runtime's subagent manager, if both exist.

    Args:
        tool_registry: The tool registry for the current run (may be None).
        client: The TaskIQClient to attach (skipped when None).
    """
    if client is None or tool_registry is None:
        return
    getter = getattr(tool_registry, "get_subagent_manager", None)
    manager = getter() if callable(getter) else None
    if manager is not None and hasattr(manager, "set_task_client"):
        manager.set_task_client(client)
