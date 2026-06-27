"""Per-run provisioning of a BlackboardHandle (flag-gated, accelerant)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def make_run_blackboard(
    config: Any,
    task_id: str,
    owner_id: str,
    session_factory: Any = None,
    *,
    redis_client: Any = None,
) -> Any | None:
    """Build a started BlackboardHandle for one run, or None when disabled/unavailable.

    The blackboard is an accelerant: any failure here returns None and the run
    proceeds without it. When redis_client is None one is created from
    config.blackboard.redis_url (caller-owned by the returned handle).
    """
    bb_cfg = getattr(config, "blackboard", None)
    if bb_cfg is None or not getattr(bb_cfg, "enabled", False):
        return None
    try:
        from atria.core.blackboard.blackboard import Blackboard, BlackboardHandle
        from atria.core.blackboard.store import BlackboardStore

        client = redis_client
        if client is None:
            import redis.asyncio as aioredis

            client = aioredis.from_url(bb_cfg.redis_url)
        store = BlackboardStore(client, task_id=task_id, ttl=bb_cfg.ttl)
        bb = Blackboard(
            store,
            thread_id=0,
            window_tokens=bb_cfg.window_tokens,
            session_factory=session_factory,
            owner_id=owner_id,
        )
        # Own the client only if WE created it (injected clients are caller-owned).
        handle = BlackboardHandle(bb, redis_client=client if redis_client is None else None)
        handle.startup()
        return handle
    except Exception as exc:  # noqa: BLE001 — accelerant, never break the run
        logger.warning("blackboard provisioning failed for %s: %s", task_id, exc)
        return None


def make_solver_blackboard(
    config: Any,
    task_id: str,
    owner_id: str,
    thread_id: int,
    *,
    session_factory: Any = None,
    redis_client: Any = None,
) -> Any | None:
    """Build a started BlackboardHandle for one parallel solver (Phase 2b).

    Unlike :func:`make_run_blackboard`, this is NOT gated on
    ``config.blackboard.enabled``: the parallel orchestrator explicitly
    provisions a shared blackboard for the job, so any solver carrying a
    ``blackboard_task_id`` gets a handle bound to that task at its own
    ``thread_id``. Returns None on any failure (accelerant — the solver
    proceeds without it).
    """
    bb_cfg = getattr(config, "blackboard", None)
    redis_url = getattr(bb_cfg, "redis_url", "redis://localhost:6379/0")
    ttl = getattr(bb_cfg, "ttl", 3600)
    window_tokens = getattr(bb_cfg, "window_tokens", 2000)
    try:
        from atria.core.blackboard.blackboard import Blackboard, BlackboardHandle
        from atria.core.blackboard.store import BlackboardStore

        client = redis_client
        if client is None:
            import redis.asyncio as aioredis

            client = aioredis.from_url(redis_url)
        store = BlackboardStore(client, task_id=task_id, ttl=ttl)
        bb = Blackboard(
            store,
            thread_id=thread_id,
            window_tokens=window_tokens,
            session_factory=session_factory,
            owner_id=owner_id,
        )
        # Own the client only if WE created it (injected clients are caller-owned).
        handle = BlackboardHandle(bb, redis_client=client if redis_client is None else None)
        handle.startup()
        return handle
    except Exception as exc:  # noqa: BLE001 — accelerant, never break the run
        logger.warning("solver blackboard provisioning failed for %s: %s", task_id, exc)
        return None


def teardown_run_blackboard(handle: Any) -> None:
    """Archive (best-effort) then shut down a run's blackboard handle. None-safe."""
    if handle is None:
        return
    try:
        handle.archive()
    except Exception as exc:  # noqa: BLE001
        logger.warning("blackboard archive on teardown failed: %s", exc)
    try:
        handle.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("blackboard shutdown failed: %s", exc)
