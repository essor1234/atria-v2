"""Per-run provisioning of a BlackboardHandle (flag-gated, accelerant)."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _make_blackboard(
    config: Any,
    task_id: str,
    owner_id: str,
    thread_id: int,
    *,
    require_enabled: bool,
    redis_client: Any = None,
) -> Any | None:
    """Build a started BlackboardHandle, or None when disabled/unavailable.

    The blackboard is an accelerant: any failure here returns None and the run
    proceeds without it. When ``require_enabled`` is True the handle is only
    built if ``config.blackboard.enabled``. When ``redis_client`` is None one is
    created from the configured redis URL (caller-owned by the returned handle).
    """
    bb_cfg = getattr(config, "blackboard", None)
    if require_enabled and (bb_cfg is None or not getattr(bb_cfg, "enabled", False)):
        return None
    redis_url = getattr(bb_cfg, "redis_url", "redis://localhost:6379/0")
    ttl = getattr(bb_cfg, "ttl", 3600)
    window_tokens = getattr(bb_cfg, "window_tokens", 2000)
    try:
        from atria.core.blackboard.blackboard import Blackboard, BlackboardHandle
        from atria.core.blackboard.store import BlackboardStore
        from atria.core.blackboard.verify_llm import build_verify_llm

        # Admission-time verifier (DeLM §A.3): cheap-model llm_call, or None when
        # disabled / no API key. None => write() skips LLM verification gracefully.
        verify_llm = build_verify_llm(config)

        client = redis_client
        if client is None:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                redis_url,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        store = BlackboardStore(client, task_id=task_id, ttl=ttl)
        bb = Blackboard(
            store,
            thread_id=thread_id,
            window_tokens=window_tokens,
            owner_id=owner_id,
            verify_llm=verify_llm,
        )
        # Own the client only if WE created it (injected clients are caller-owned).
        handle = BlackboardHandle(bb, redis_client=client if redis_client is None else None)
        handle.startup()
        return handle
    except Exception as exc:  # noqa: BLE001 — accelerant, never break the run
        logger.warning("blackboard provisioning failed for %s: %s", task_id, exc)
        return None


def make_run_blackboard(
    config: Any,
    task_id: str,
    owner_id: str,
    *,
    redis_client: Any = None,
) -> Any | None:
    """Build a started BlackboardHandle for one run (flag-gated), or None."""
    return _make_blackboard(
        config,
        task_id,
        owner_id,
        thread_id=0,
        require_enabled=True,
        redis_client=redis_client,
    )


def make_solver_blackboard(
    config: Any,
    task_id: str,
    owner_id: str,
    thread_id: int,
    *,
    redis_client: Any = None,
) -> Any | None:
    """Build a started BlackboardHandle for one parallel solver (Phase 2b).

    Unlike :func:`make_run_blackboard`, this is NOT gated on
    ``config.blackboard.enabled``: the parallel orchestrator explicitly
    provisions a shared blackboard for the job, so any solver carrying a
    ``blackboard_task_id`` gets a handle bound to that task at its own
    ``thread_id``.
    """
    return _make_blackboard(
        config,
        task_id,
        owner_id,
        thread_id=thread_id,
        require_enabled=False,
        redis_client=redis_client,
    )


def teardown_run_blackboard(handle: Any) -> None:
    """Shut down a run's blackboard handle. None-safe.

    The shared context is ephemeral problem state (it lives in Redis with a TTL);
    there is no durable archive — see the removed Postgres path.
    """
    if handle is None:
        return
    try:
        handle.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("blackboard shutdown failed: %s", exc)
