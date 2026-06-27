"""Two-phase parallel-solve orchestration: start (fan-out) and collect (judge + apply)."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from atria.core.parallel.apply import apply_diff
from atria.core.parallel.candidate import extract_candidate
from atria.core.parallel.job_store import JobStore
from atria.core.parallel.judge import judge_candidates
from atria.core.parallel.snapshot import snapshot_worktree

logger = logging.getLogger(__name__)


class ParallelOrchestrator:
    """Fan out N worktree-isolated solvers, judge their candidates, apply the winner."""

    def __init__(
        self,
        task_client: Any,        # Sub-project 1 TaskIQClient (sync enqueue/await)
        worktree_manager: Any,   # atria.core.git.worktree.WorktreeManager
        job_store: JobStore,
        redis_client: Any,       # async redis for reading the blackboard notes at collect
        llm_call: Callable[[str, str], str],
        config: Any,             # ParallelConfig
        run_async: Callable[[Any], Any],  # helper to run a coroutine from this sync context
    ) -> None:
        self._tc = task_client
        self._wm = worktree_manager
        self._js = job_store
        self._redis = redis_client
        self._llm = llm_call
        self._cfg = config
        self._run_async = run_async

    def start(self, task: str, n: int, repo_dir: str, owner_id: str, session_id: str) -> str:
        """Snapshot the tree, fan out N worktree-isolated solvers, persist the job record."""
        n = max(2, min(int(n or self._cfg.default_solvers), self._cfg.max_solvers))
        job_id = uuid.uuid4().hex[:12]
        base_ref = snapshot_worktree(repo_dir)
        blackboard_task_id = "bb_" + job_id
        worktree_names: list[str] = []
        worktree_paths: list[str] = []
        task_ids: list[str] = []
        try:
            from atria.core.tasks.payload import SubagentTaskPayload

            for i in range(n):
                wt = self._wm.create(base_branch=base_ref)
                if wt is None:
                    raise RuntimeError("worktree creation failed")
                worktree_names.append(wt.branch.replace("worktree-", ""))
                worktree_paths.append(wt.path)
                payload = SubagentTaskPayload(
                    session_id=session_id, owner_id=owner_id, subagent_type="solver",
                    prompt=task, working_dir=wt.path, config_snapshot={},
                    blackboard_task_id=blackboard_task_id, thread_id=i,
                )
                task_ids.append(self._tc.enqueue(payload))
            self._run_async(self._js.save(job_id, {
                "task_ids": task_ids, "worktree_names": worktree_names,
                "worktree_paths": worktree_paths, "blackboard_task_id": blackboard_task_id,
                "base_ref": base_ref, "repo_dir": repo_dir, "n": n, "task": task,
            }, ttl=self._cfg.pjob_ttl))
            return job_id
        except Exception:
            for name in worktree_names:
                try:
                    self._wm.remove(name, force=True)
                except Exception:  # noqa: BLE001
                    pass
            raise

    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        """Await the solvers; once all are done, judge candidates and apply the winner."""
        rec = self._run_async(self._js.load(job_id))
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}
        # Await all solvers concurrently (they share the task client's loop); a
        # thread pool keeps wall-clock ~= the slowest solver, not their sum.
        task_ids = rec["task_ids"]
        with ThreadPoolExecutor(max_workers=len(task_ids)) as ex:
            results = list(
                ex.map(
                    lambda tid: self._tc.await_result(tid, block=block, timeout_ms=timeout_ms),
                    task_ids,
                )
            )
        done = [r for r in results if r.get("status") == "done"]
        if len(done) < len(results):
            return {"status": "running", "done": len(done), "n": rec["n"]}
        try:
            notes = self._read_notes(rec["blackboard_task_id"])
            candidates = [
                extract_candidate(rec["worktree_paths"][i], rec["base_ref"], notes, i)
                for i, r in enumerate(results) if r.get("success")
            ]
            dropped = [i for i, r in enumerate(results) if not r.get("success")]
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
            return {
                "status": "done", "applied": applied, "winner_thread": winner_thread,
                "conflicted_files": conflicted, "reasoning": verdict.reasoning,
                "dropped_threads": dropped,
                "candidates": [{"thread": c.thread_id, "ok": c.ok, "summary": c.patch_summary}
                               for c in candidates],
                # NOTE: base_ref retained for recovery; not discarded here.
                "snapshot_ref": rec["base_ref"],
            }
        finally:
            for name in rec["worktree_names"]:
                try:
                    self._wm.remove(name, force=True)
                except Exception:  # noqa: BLE001
                    pass
            self._run_async(self._js.delete(job_id))

    def _read_notes(self, blackboard_task_id: str) -> list:
        from atria.core.blackboard.store import BlackboardStore

        store = BlackboardStore(self._redis, task_id=blackboard_task_id, ttl=self._cfg.pjob_ttl)
        return self._run_async(store.read_all())
