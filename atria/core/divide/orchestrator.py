"""Divide-work coordinator: decompose → schedule → gather. Worker I/O is injected."""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from atria.core.divide.decompose import DecomposeError, decompose
from atria.core.divide.job_store import JobStore
from atria.core.divide.models import DivideJob, DivideTask
from atria.core.divide.scheduler import schedule
from atria.core.modules.subagent import build_module_gateway_block
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


class DivideOrchestrator:
    """Run one divide-work job. Enqueue/await callables decouple it from TaskIQ."""

    def __init__(
        self,
        job_store: JobStore,
        redis_client: Any,
        llm_call: Callable[[str, str], str],
        config: Any,
        run_async: Callable[[Any], Any],
        enqueue_worker: Callable[[SubagentTaskPayload], Awaitable[str]],
        await_worker: Callable[[list[str]], Awaitable[tuple[str, dict]]],
        modules_root: str,
        owner_id: str,
        session_id: str,
        progress_cb: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._js = job_store
        self._redis = redis_client
        self._llm = llm_call
        self._cfg = config
        self._run_async = run_async
        self._enqueue = enqueue_worker
        self._await = await_worker
        self._root = modules_root
        self._owner = owner_id
        self._session = session_id
        self._cb = progress_cb

    def _emit(self, stage: str, data: dict) -> None:
        if self._cb is None:
            return
        try:
            self._cb(stage, data)
        except Exception as exc:  # noqa: BLE001 — telemetry never breaks the job
            logger.warning("divide progress_cb failed at %s: %s", stage, exc)

    def start(self, request: str, module: Any, module_skill: str) -> str:
        return self._run_async(self.start_async(request, module, module_skill))

    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        return self._run_async(self.collect_async(job_id))

    async def start_async(self, request: str, module: Any, module_skill: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        module_name = getattr(module, "name", str(module))
        bb_id = "dw_" + job_id
        job = DivideJob(job_id=job_id, module=module_name, request=request,
                        blackboard_task_id=bb_id, status="decomposing")
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        try:
            tasks = decompose(request, module_skill, self._llm, self._cfg.max_tasks)
        except DecomposeError as exc:
            job.status = "failed"
            job.summary = f"decompose failed: {exc}"
            await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
            self._emit("done", {"job_id": job_id, "status": "failed", "summary": job.summary})
            return job_id

        job.tasks = tasks
        job.status = "running"
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        self._emit("started", {
            "job_id": job_id, "module": module_name, "request": request,
            "tasks": [{"id": t.id, "description": t.description, "depends_on": t.depends_on}
                      for t in tasks],
        })

        gateway = build_module_gateway_block(module, Path(self._root)) \
            if not isinstance(module, str) else module_skill
        by_id = {t.id: t for t in tasks}

        async def enqueue(t: DivideTask) -> str:
            parents = "\n".join(f"- {by_id[d].id}: {by_id[d].result or ''}" for d in t.depends_on)
            prompt = (
                f"{gateway}\n\n## Your subtask\n{t.description}\n\n"
                + (f"## Upstream results\n{parents}\n" if parents else "")
            )
            payload = SubagentTaskPayload(
                session_id=self._session, owner_id=self._owner,
                subagent_type="module_worker", prompt=prompt,
                working_dir=self._root, config_snapshot={},
                blackboard_task_id=bb_id, thread_id=int(t.id.lstrip("t") or 0)
                if t.id.lstrip("t").isdigit() else 0,
            )
            return await self._enqueue(payload)

        async def on_change(t: DivideTask) -> None:
            await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
            self._emit("task_update", {"job_id": job_id, "task_id": t.id,
                                       "status": t.status, "result": t.result})

        await schedule(tasks, enqueue, self._await, self._cfg.max_parallel, on_change)

        n_done = sum(1 for t in tasks if t.status == "done")
        n_fail = sum(1 for t in tasks if t.status in ("failed", "skipped"))
        job.status = "done"
        job.summary = f"{n_done}/{len(tasks)} tasks done, {n_fail} failed/skipped."
        await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
        self._emit("done", {"job_id": job_id, "status": "done", "summary": job.summary})
        return job_id

    async def collect_async(self, job_id: str) -> dict:
        rec = await self._js.load(job_id)
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}
        return rec
