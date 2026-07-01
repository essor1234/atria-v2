"""Divide-work coordinator: decompose → schedule → gather. Worker I/O is injected."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from atria.core.divide.decompose import DecomposeError, decompose, redecompose
from atria.core.orchestration.job_store import JobStore
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
        """Fire-and-forget: decompose + emit ``started`` synchronously, then run
        workers on the background loop. Returns ``job_id`` as soon as the DAG
        has been persisted and announced. Workers complete asynchronously and
        emit ``done`` when they finish.
        """
        return self._run_async(self.start_async(request, module, module_skill))

    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        return self._run_async(self.collect_async(job_id))

    async def start_async(self, request: str, module: Any, module_skill: str) -> str:
        """Decompose + persist + emit ``started``. Schedule workers as a
        background task on the current loop and return immediately.
        """
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

        # Fire-and-forget: workers run on the current loop; the coroutine
        # scheduled here owns the rest of the lifecycle (schedule +
        # redecompose + emit done). The caller sees ``job_id`` immediately.
        asyncio.create_task(
            self._run_workers(job_id, job, tasks, module, module_skill, bb_id, request)
        )
        return job_id

    async def _run_workers(
        self,
        job_id: str,
        job: DivideJob,
        tasks: list,
        module: Any,
        module_skill: str,
        bb_id: str,
        request: str,
    ) -> None:
        """Background worker loop for one divide job.

        Schedules the DAG through the task client, drives any re-decomposition
        rounds allowed by config, and emits ``done`` when the DAG drains.
        Never re-raises: unhandled failures are logged and end the job with a
        ``failed`` status so the UI stops pulsing.
        """
        try:
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

            # DeLM stage 4: re-decomposition rounds after the queue drains.
            rounds = getattr(self._cfg, "max_redecompose_rounds", 1)
            for _ in range(max(0, rounds)):
                digest = await self._read_digest(bb_id)
                completed = "; ".join(f"{t.id}[{t.status}]" for t in tasks)
                new_tasks = redecompose(
                    request, module_skill, completed, digest,
                    {t.id for t in tasks}, self._llm, self._cfg.max_tasks,
                )
                if not new_tasks:
                    break
                tasks.extend(new_tasks)
                by_id.update({t.id: t for t in new_tasks})
                job.tasks = tasks
                await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
                self._emit("redecomposed", {
                    "job_id": job_id,
                    "new_tasks": [{"id": t.id, "description": t.description,
                                   "depends_on": t.depends_on} for t in new_tasks],
                })
                await schedule(tasks, enqueue, self._await, self._cfg.max_parallel, on_change)

            n_done = sum(1 for t in tasks if t.status == "done")
            n_fail = sum(1 for t in tasks if t.status in ("failed", "skipped"))
            job.status = "done"
            job.summary = f"{n_done}/{len(tasks)} tasks done, {n_fail} failed/skipped."
            await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
            self._emit("done", {"job_id": job_id, "status": "done", "summary": job.summary})
        except Exception as exc:  # noqa: BLE001 — background task must never crash silently
            logger.exception("divide workers crashed for %s: %s", job_id, exc)
            try:
                job.status = "failed"
                job.summary = f"workers crashed: {exc}"
                await self._js.save(job_id, job.model_dump(), ttl=self._cfg.pjob_ttl)
                self._emit("done", {"job_id": job_id, "status": "failed", "summary": job.summary})
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass

    async def _read_digest(self, bb_id: str) -> str:
        """Render the current shared-context digest for re-decomposition, or "" on error."""
        try:
            from atria.core.blackboard.render import render_digest
            from atria.core.blackboard.store import BlackboardStore

            store = BlackboardStore(self._redis, task_id=bb_id, ttl=self._cfg.pjob_ttl)
            notes = await store.read_all()
            return render_digest(notes, viewer_id=0, window_tokens=2000)
        except Exception as exc:  # noqa: BLE001 — digest is advisory, never break the job
            logger.warning("divide read digest failed for %s: %s", bb_id, exc)
            return ""

    async def collect_async(self, job_id: str) -> dict:
        rec = await self._js.load(job_id)
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}
        return rec
