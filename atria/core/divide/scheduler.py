"""Dependency-aware schedule loop for a divide-work DAG. Worker-agnostic via injected callables."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from atria.core.divide.models import DivideTask

logger = logging.getLogger(__name__)

EnqueueFn = Callable[[DivideTask], Awaitable[str]]
AwaitOneFn = Callable[[list[str]], Awaitable[tuple[str, dict]]]
OnChangeFn = Callable[[DivideTask], Awaitable[None]]


async def _notify(on_change: OnChangeFn | None, task: DivideTask) -> None:
    if on_change is None:
        return
    try:
        await on_change(task)
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks scheduling
        logger.warning("divide on_change failed: %s", exc)


async def schedule(
    tasks: list[DivideTask],
    enqueue: EnqueueFn,
    await_one: AwaitOneFn,
    max_parallel: int,
    on_change: OnChangeFn | None = None,
) -> list[DivideTask]:
    """Run the DAG: enqueue ready tasks (≤ max_parallel), await, unlock, skip-on-fail."""
    by_id = {t.id: t for t in tasks}
    inflight: dict[str, DivideTask] = {}  # task_id -> task

    def _deps_done(t: DivideTask) -> bool:
        return all(by_id[d].status == "done" for d in t.depends_on)

    def _dep_failed(t: DivideTask) -> bool:
        return any(by_id[d].status in ("failed", "skipped") for d in t.depends_on)

    while True:
        # Mark tasks whose deps failed as skipped.
        for t in tasks:
            if t.status == "pending" and _dep_failed(t):
                t.status = "skipped"
                await _notify(on_change, t)
        # Enqueue ready tasks up to the parallel cap.
        for t in tasks:
            if len(inflight) >= max_parallel:
                break
            if t.status == "pending" and _deps_done(t):
                t.status = "running"
                await _notify(on_change, t)
                tid = await enqueue(t)
                t.task_id = tid
                inflight[tid] = t
        if not inflight:
            # Nothing running: done when no pending remain.
            if not any(t.status == "pending" for t in tasks):
                break
            continue  # only blocked-by-skip remain; loop marks them skipped
        tid, result = await await_one(list(inflight.keys()))
        t = inflight.pop(tid, None)
        if t is None:
            continue
        if result.get("status") == "done":
            t.status = "done"
            t.result = str(result.get("output") or result.get("summary") or "")
        else:
            t.status = "failed"
            t.result = str(result.get("error") or "worker failed")
        await _notify(on_change, t)
    return tasks
