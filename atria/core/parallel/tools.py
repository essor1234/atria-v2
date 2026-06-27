"""Tool handlers + orchestrator builder for solve_parallel / get_parallel_result.

The orchestrator bridges the (loopless) agent thread to async work (Redis job
store + blackboard reads) via a persistent daemon-thread event loop, mirroring
the shape of ``TaskIQClient``/``BlackboardHandle``.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from atria.core.parallel.job_store import JobStore
from atria.core.parallel.orchestrator import ParallelOrchestrator

logger = logging.getLogger(__name__)


class _LoopRunner:
    """Persistent daemon-thread event loop; run coroutines synchronously."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


def build_orchestrator(
    task_client: Any,
    worktree_manager: Any,
    config: Any,
    llm_call: Callable[[str, str], str],
    redis_client: Any = None,
) -> ParallelOrchestrator:
    """Construct a ParallelOrchestrator from a run's task client + helpers.

    Args:
        task_client: The run's TaskIQClient (sync enqueue/await).
        worktree_manager: A WorktreeManager bound to the repo.
        config: The AppConfig (its ``.parallel`` section configures the orchestrator).
        llm_call: Callable (system, user) -> assistant_text for the judge.
        redis_client: Optional async redis client; one is created from
            ``config.parallel.redis_url`` when omitted (caller/runner-owned).
    """
    runner = _LoopRunner()
    parallel_cfg = getattr(config, "parallel", None) or config
    if redis_client is None:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(getattr(parallel_cfg, "redis_url", "redis://localhost:6379/0"))
    job_store = JobStore(redis_client)
    return ParallelOrchestrator(
        task_client=task_client,
        worktree_manager=worktree_manager,
        job_store=job_store,
        redis_client=redis_client,
        llm_call=llm_call,
        config=parallel_cfg,
        run_async=runner.run,
    )


def make_worktree_manager(repo_dir: str) -> Any:
    """Build a WorktreeManager bound to ``repo_dir``."""
    from atria.core.git.worktree import WorktreeManager

    return WorktreeManager(Path(repo_dir))


def execute_solve_parallel(
    arguments: dict,
    orchestrator: ParallelOrchestrator,
    repo_dir: str,
    owner_id: str,
    session_id: str,
) -> dict:
    """Fan out N solvers for a task. Returns {job_id, status, n}."""
    task = arguments.get("task") or arguments.get("prompt") or ""
    if not task:
        return {"success": False, "error": "task is required", "output": None}
    n = arguments.get("n")
    try:
        job_id = orchestrator.start(
            task=task, n=n, repo_dir=repo_dir, owner_id=owner_id, session_id=session_id
        )
    except Exception as exc:  # noqa: BLE001 — surface as a tool error, never crash the loop
        logger.warning("solve_parallel start failed: %s", exc)
        return {"success": False, "error": f"solve_parallel failed: {exc}", "output": None}
    return {
        "success": True,
        "job_id": job_id,
        "status": "running",
        "output": (
            f"[PARALLEL STARTED] job_id={job_id}. "
            "Use get_parallel_result(job_id) to judge + apply the winner."
        ),
    }


def execute_get_parallel_result(arguments: dict, orchestrator: ParallelOrchestrator) -> dict:
    """Await solvers; once all done, judge candidates and apply the winner."""
    job_id = arguments.get("job_id", "")
    if not job_id:
        return {"success": False, "error": "job_id is required", "output": None}
    block = arguments.get("block", True)
    timeout = arguments.get("timeout", 30000)
    try:
        result = orchestrator.collect(job_id, block=block, timeout_ms=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_parallel_result collect failed: %s", exc)
        return {"success": False, "error": f"get_parallel_result failed: {exc}", "output": None}
    return {"success": result.get("status") != "unknown", "output": result, **result}
