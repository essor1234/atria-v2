"""Tool handlers + orchestrator builder for divide_work / get_divide_result.

Mirrors atria/core/parallel/tools.py. divide_work starts a coordinator that
decomposes a request into sub-tasks and fans them out over the task client's
broker; get_divide_result reads current job state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from atria.core.divide.orchestrator import DivideOrchestrator
from atria.core.orchestration.bridge import ensure_async_redis, make_run_async
from atria.core.orchestration.gating import assess_heavy_path
from atria.core.orchestration.job_store import DIVIDE_PREFIX, JobStore
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


def build_divide_orchestrator(
    task_client: Any,
    config: Any,
    llm_call: Callable[[str, str], str],
    modules_root: str,
    owner_id: str,
    session_id: str,
    progress_cb: Callable[[str, dict], None] | None = None,
    redis_client: Any = None,
) -> DivideOrchestrator:
    """Construct a DivideOrchestrator that fans workers out over the task client's broker.

    Args:
        task_client: The run's TaskIQClient. Its persistent event loop is reused.
        config: The AppConfig (its ``.divide`` section configures the orchestrator).
        llm_call: Callable (system, user) -> assistant_text for decomposition.
        modules_root: Absolute path to the modules directory.
        owner_id: Owner identifier for job scoping.
        session_id: Session identifier for job scoping.
        progress_cb: Optional progress callback (str event_type, dict payload).
        redis_client: Optional async redis client; created from config when omitted.

    Returns:
        A configured DivideOrchestrator ready to start jobs.
    """
    divide_cfg = getattr(config, "divide", None) or config
    run_async = make_run_async(task_client)
    redis_client = ensure_async_redis(
        redis_client, getattr(divide_cfg, "redis_url", "redis://localhost:6379/0")
    )

    broker = task_client._broker

    async def enqueue_worker(payload: SubagentTaskPayload) -> str:
        from atria.core.tasks.client import _TASK_NAME
        from atria.core.tasks import meta

        task = broker.find_task(_TASK_NAME)
        if task is None:
            raise RuntimeError(f"task {_TASK_NAME} not registered")
        kicked = await task.kiq(payload.model_dump())
        await meta.record_enqueue(redis_client, kicked.task_id, payload.session_id)
        return kicked.task_id

    async def await_worker(task_ids: list[str]) -> tuple[str, dict]:
        backend = broker.result_backend
        while True:
            for tid in task_ids:
                if await backend.is_result_ready(tid):
                    res = await backend.get_result(tid, with_logs=False)
                    if res.is_err:
                        return tid, {"status": "failed", "error": str(res.error)}
                    val = res.return_value or {}
                    return tid, {**val, "status": "done"}
            await asyncio.sleep(0.25)

    orch = DivideOrchestrator(
        job_store=JobStore(redis_client, DIVIDE_PREFIX),
        redis_client=redis_client,
        llm_call=llm_call,
        config=divide_cfg,
        run_async=run_async,
        enqueue_worker=enqueue_worker,
        await_worker=await_worker,
        modules_root=modules_root,
        owner_id=owner_id,
        session_id=session_id,
        progress_cb=progress_cb,
    )
    # S5: low-ROI advisory for strong base models (assessed against the full AppConfig).
    orch._advisory = assess_heavy_path(config)
    return orch


def execute_divide_work(
    arguments: dict,
    orchestrator: DivideOrchestrator,
    module: Any,
    module_skill: str,
) -> dict:
    """Decompose + dispatch a divide-work job.

    Args:
        arguments: Tool call arguments. Must contain ``request``.
        orchestrator: The DivideOrchestrator for this run.
        module: The module object or name to decompose the request against.
        module_skill: The SKILL.md text for the module.

    Returns:
        Dict with keys ``success``, ``job_id``, ``status``, ``output``.
    """
    request = arguments.get("request") or arguments.get("task") or ""
    if not request:
        return {"success": False, "error": "request is required", "output": None}
    try:
        job_id = orchestrator.start(request, module, module_skill)
    except Exception as exc:  # noqa: BLE001 — surface as tool error, never crash the loop
        logger.warning("divide_work start failed: %s", exc)
        return {"success": False, "error": f"divide_work failed: {exc}", "output": None}
    advisory = getattr(orchestrator, "_advisory", "")
    output = (
        f"[DIVIDE STARTED] job_id={job_id}. "
        "Use get_solve_result(job_id) to poll progress and collect results."
    )
    if advisory:
        output += f"\n{advisory}"
    return {
        "success": True,
        "job_id": job_id,
        "status": "running",
        "output": output,
    }


def execute_get_divide_result(arguments: dict, orchestrator: DivideOrchestrator) -> dict:
    """Return current job state (tasks + summary).

    Args:
        arguments: Tool call arguments. Must contain ``job_id``.
        orchestrator: The DivideOrchestrator for this run.

    Returns:
        Dict with keys ``success`` and ``output`` (the job state dict).
    """
    job_id = arguments.get("job_id", "")
    if not job_id:
        return {"success": False, "error": "job_id is required", "output": None}
    try:
        result = orchestrator.collect(
            job_id,
            block=arguments.get("block", True),
            timeout_ms=arguments.get("timeout", 30000),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_divide_result failed: %s", exc)
        return {"success": False, "error": f"get_divide_result failed: {exc}", "output": None}
    return {"success": result.get("status") != "unknown", "output": result}
