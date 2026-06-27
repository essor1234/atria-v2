"""The background-subagent TaskIQ task. Runs in the worker process."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from atria.core.agents.deps_builder import build_runtime_and_deps
from atria.core.tasks.broker import broker
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


def _run_subagent_sync(runtime_suite: Any, deps: Any, payload: SubagentTaskPayload) -> dict:
    """Run the subagent synchronously via the manager.

    Blocking; called inside asyncio.to_thread so the worker's event loop stays
    responsive. Fire-and-collect: returns the final result dict only.
    """
    manager = runtime_suite.tool_registry.get_subagent_manager()
    if manager is None:
        return {
            "success": False,
            "content": "no subagent manager available in worker runtime",
            "messages": [],
            "completion_status": "error",
        }
    result = manager.execute_subagent(
        name=payload.subagent_type,
        task=payload.prompt,
        deps=deps,
        show_spawn_header=False,
        tool_call_id=payload.parent_tool_call_id,
        working_dir=payload.working_dir,
        path_mapping=payload.path_mapping or None,
    )
    return {
        "success": bool(result.get("success")),
        "content": result.get("content", ""),
        "messages": result.get("messages", []),
        "completion_status": result.get("completion_status", "success"),
    }


@broker.task(task_name="atria.core.tasks.tasks.run_background_subagent")
async def run_background_subagent(payload: dict) -> dict:
    """Rebuild a headless runtime from the payload and run the subagent."""
    p = SubagentTaskPayload.model_validate(payload)
    deps: Any = None
    try:
        runtime_suite, deps = build_runtime_and_deps(p)
        return await asyncio.to_thread(_run_subagent_sync, runtime_suite, deps, p)
    except Exception as exc:  # noqa: BLE001
        logger.exception("background subagent failed: %s", exc)
        return {
            "success": False,
            "content": f"background subagent failed: {exc}",
            "messages": [],
            "completion_status": "error",
        }
    finally:
        # Blackboard (Phase 2b): archive (best-effort) + shut down a solver's handle.
        handle = getattr(deps, "blackboard", None) if deps is not None else None
        if handle is not None:
            from atria.core.blackboard.provision import teardown_run_blackboard

            teardown_run_blackboard(handle)
