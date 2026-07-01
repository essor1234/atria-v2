"""Parallel-solve orchestration: staggered solver waves over a shared verified context.

DeLM (Table 1) shows that running parallel attempts in *full isolation* and merging a single
winner (AOrchestra-Parallel) underperforms DeLM, whose value is that a later attempt reads an
earlier attempt's verified findings and redirects (the §4.2.1 t0→t1 trace). This orchestrator
realizes that by enqueuing the N solvers in sequential **waves**: each wave shares one
blackboard, so a wave-k solver builds its prompt with the verified notes (FAILs, FACTs,
PATCH_SUMMARYs) written by waves 1..k-1. After all waves finish, the judge picks the best
candidate across every wave and the winner's diff is applied.

``waves=1`` restores the original single simultaneous fan-out.
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from atria.core.orchestration.job_store import JobStore
from atria.core.parallel.apply import apply_diff
from atria.core.parallel.candidate import extract_candidate
from atria.core.parallel.judge import judge_candidates
from atria.core.parallel.snapshot import snapshot_worktree
from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


def plan_waves(n: int, waves: int) -> list[int]:
    """Split ``n`` solvers into ``waves`` sequential groups (bigger waves first).

    Bigger-first front-loads broad exploration to seed the shared context, leaving later
    (smaller) waves to refine using those notes. ``waves`` is clamped to ``[1, n]``.
    """
    waves = max(1, min(int(waves or 1), n))
    base, rem = divmod(n, waves)
    return [base + (1 if i < rem else 0) for i in range(waves)]


class ParallelOrchestrator:
    """Run N solvers in staggered waves on a shared blackboard, judge, apply the winner."""

    def __init__(
        self,
        task_client: Any,        # Sub-project 1 TaskIQClient (sync enqueue/await)
        worktree_manager: Any,   # atria.core.git.worktree.WorktreeManager
        job_store: JobStore,
        redis_client: Any,       # async redis for reading the blackboard notes
        llm_call: Callable[[str, str], str],
        config: Any,             # ParallelConfig
        run_async: Callable[[Any], Any],  # run a coroutine from this sync context
        progress_cb: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._tc = task_client
        self._wm = worktree_manager
        self._js = job_store
        self._redis = redis_client
        self._llm = llm_call
        self._cfg = config
        self._run_async = run_async
        self._progress_cb = progress_cb

    def _emit(self, stage: str, data: dict) -> None:
        """Best-effort progress notification; never raises into the solve path."""
        if self._progress_cb is None:
            return
        try:
            self._progress_cb(stage, data)
        except Exception as exc:  # noqa: BLE001 — telemetry must never break solving
            logger.warning("parallel progress_cb failed at %s: %s", stage, exc)

    # -- enqueue ----------------------------------------------------------------- #
    def _enqueue_wave(self, rec: dict, size: int) -> list[str]:
        """Create ``size`` worktrees off the base snapshot and enqueue their solvers.

        Solvers are appended to ``rec['solvers']`` (thread_id, name, path, task_id). Returns
        the task_ids enqueued for this wave. Each solver reads the shared blackboard at
        prompt-build time, so a later wave sees earlier waves' verified notes.
        """
        wave_task_ids: list[str] = []
        for _ in range(size):
            thread_id = rec["next_thread_id"]
            wt = self._wm.create(base_branch=rec["base_ref"])
            if wt is None:
                raise RuntimeError("worktree creation failed")
            name = wt.branch.replace("worktree-", "")
            payload = SubagentTaskPayload(
                session_id=rec["session_id"], owner_id=rec["owner_id"],
                subagent_type="solver", prompt=rec["task"], working_dir=wt.path,
                config_snapshot={}, blackboard_task_id=rec["blackboard_task_id"],
                thread_id=thread_id,
            )
            task_id = self._tc.enqueue(payload)
            rec["solvers"].append(
                {"thread_id": thread_id, "name": name, "path": wt.path, "task_id": task_id}
            )
            rec["next_thread_id"] = thread_id + 1
            wave_task_ids.append(task_id)
        return wave_task_ids

    def start(self, task: str, n: int, repo_dir: str, owner_id: str, session_id: str) -> str:
        """Snapshot the tree, enqueue wave 1, persist the job record."""
        n = max(2, min(int(n or self._cfg.default_solvers), self._cfg.max_solvers))
        job_id = uuid.uuid4().hex[:12]
        base_ref = snapshot_worktree(repo_dir)
        wave_sizes = plan_waves(n, getattr(self._cfg, "waves", 2))
        rec: dict = {
            "task": task, "n": n, "repo_dir": repo_dir, "base_ref": base_ref,
            "blackboard_task_id": "bb_" + job_id, "owner_id": owner_id,
            "session_id": session_id, "wave_sizes": wave_sizes, "wave_index": 0,
            "next_thread_id": 0, "solvers": [], "inflight": [],
        }
        try:
            rec["inflight"] = self._enqueue_wave(rec, wave_sizes[0])
            self._run_async(self._js.save(job_id, rec, ttl=self._cfg.pjob_ttl))
            self._emit("started", {
                "job_id": job_id, "n": n, "task": task, "wave_sizes": wave_sizes,
                "worktree_names": [s["name"] for s in rec["solvers"]],
            })
            return job_id
        except Exception:
            for s in rec["solvers"]:
                try:
                    self._wm.remove(s["name"], force=True)
                except Exception:  # noqa: BLE001
                    pass
            raise

    # -- collect ----------------------------------------------------------------- #
    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        """Await the current wave; advance through remaining waves; judge + apply winner."""
        rec = self._run_async(self._js.load(job_id))
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}

        while True:
            results = self._await_inflight(rec["inflight"], block=block, timeout_ms=timeout_ms)
            done = [r for r in results.values() if r.get("status") == "done"]
            if len(done) < len(rec["inflight"]):
                self._emit("progress", {
                    "job_id": job_id, "wave": rec["wave_index"] + 1,
                    "waves": len(rec["wave_sizes"]), "done": len(done),
                    "n_wave": len(rec["inflight"]),
                })
                return {"status": "running", "wave": rec["wave_index"] + 1,
                        "waves": len(rec["wave_sizes"]), "done": len(done), "n": rec["n"]}
            # Current wave complete — advance to the next wave if any remain.
            if rec["wave_index"] + 1 < len(rec["wave_sizes"]):
                rec["wave_index"] += 1
                size = rec["wave_sizes"][rec["wave_index"]]
                rec["inflight"] = self._enqueue_wave(rec, size)
                self._run_async(self._js.save(job_id, rec, ttl=self._cfg.pjob_ttl))
                self._emit("wave", {
                    "job_id": job_id, "wave": rec["wave_index"] + 1,
                    "waves": len(rec["wave_sizes"]), "n_wave": size,
                })
                if not block:
                    return {"status": "running", "wave": rec["wave_index"] + 1,
                            "waves": len(rec["wave_sizes"]), "done": 0, "n": rec["n"]}
                continue
            break  # all waves done

        return self._finalize(job_id, rec)

    def _await_inflight(self, task_ids: list[str], block: bool, timeout_ms: int) -> dict:
        """Await the given task_ids concurrently; return {task_id: result_dict}."""
        if not task_ids:
            return {}
        with ThreadPoolExecutor(max_workers=len(task_ids)) as ex:
            results = list(ex.map(
                lambda tid: (tid, self._tc.await_result(tid, block=block, timeout_ms=timeout_ms)),
                task_ids,
            ))
        return dict(results)

    def _finalize(self, job_id: str, rec: dict) -> dict:
        """All waves done: extract every solver's candidate, judge, apply the winner."""
        try:
            notes = self._read_notes(rec["blackboard_task_id"])
            results = self._await_inflight_all(rec)
            candidates = []
            dropped: list[int] = []
            for s in rec["solvers"]:
                r = results.get(s["task_id"], {})
                if r.get("success"):
                    candidates.append(
                        extract_candidate(s["path"], rec["base_ref"], notes, s["thread_id"])
                    )
                else:
                    dropped.append(s["thread_id"])
            verdict = judge_candidates(rec["task"], candidates, self._llm)
            applied = False
            conflicted: list[str] = []
            winner_thread = -1
            if verdict.winner_index >= 0:
                winner = candidates[verdict.winner_index]
                winner_thread = winner.thread_id
                ar = apply_diff(rec["repo_dir"], winner.diff)
                applied = ar.ok
                conflicted = ar.conflicted_files
            result = {
                "status": "done", "applied": applied, "winner_thread": winner_thread,
                "conflicted_files": conflicted, "reasoning": verdict.reasoning,
                "dropped_threads": dropped, "waves": len(rec["wave_sizes"]),
                "candidates": [{"thread": c.thread_id, "ok": c.ok, "summary": c.patch_summary}
                               for c in candidates],
                "snapshot_ref": rec["base_ref"],  # retained for recovery, not discarded
                "job_id": job_id,
            }
            self._emit("done", result)
            return result
        finally:
            for s in rec["solvers"]:
                try:
                    self._wm.remove(s["name"], force=True)
                except Exception:  # noqa: BLE001
                    pass
            self._run_async(self._js.delete(job_id))

    def _await_inflight_all(self, rec: dict) -> dict:
        """Collect final results for every solver across all waves (all already complete)."""
        return self._await_inflight(
            [s["task_id"] for s in rec["solvers"]], block=True, timeout_ms=30000
        )

    def _read_notes(self, blackboard_task_id: str) -> list:
        from atria.core.blackboard.store import BlackboardStore

        store = BlackboardStore(self._redis, task_id=blackboard_task_id, ttl=self._cfg.pjob_ttl)
        return self._run_async(store.read_all())
