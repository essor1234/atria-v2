# DeLM Parallel Solvers + Judge — Design (Sub-project 2, Phase 2b)

**Date:** 2026-06-27
**Status:** Approved design, pending implementation plan
**Scope:** Phase 2b of Sub-project 2 — the `solve_parallel` fan-out, git-worktree-isolated
solvers, the LLM judge, and apply-winner. Built on Sub-project 1 (TaskIQ background
subagents) and Phase 2a (shared verified blackboard).

## Context

DeLM runs N solver threads on one task; each owns an isolated workspace and writes verified
typed notes to a shared blackboard, and one workspace's result is selected (by oracle reward
in DeLM). Phase 2b adapts this to atria: N **autonomous background subagents** (Sub-project 1),
each in its own **git worktree**, each with the Phase 2a **blackboard** attached; an **LLM
judge** selects the best of N candidate solutions and applies the winner's diff to the user's
workspace.

### Decisions locked during brainstorming

- **Judge basis:** an LLM judge over the N worktree diffs + each solver's verified
  `PATCH_SUMMARY` evidence/risk. No universal test command (atria is a general agent); the
  deterministic verifier already guarantees PATCH_SUMMARY evidence is a real, run check.
- **Worktree base:** snapshot the user's current state **including uncommitted changes**, and
  fork all N worktrees from that snapshot. Snapshot is discarded after.
- **Return model:** non-blocking — `solve_parallel(task, n)` returns a `job_id`; the agent
  collects later via `get_parallel_result(job_id)` (mirrors Sub-project 1 fire-and-collect).
- **Approach:** A — reuse the Sub-project 1 substrate (enqueue N existing background-subagent
  tasks) + the existing `WorktreeManager` + Phase 2a blackboard; add only a thin orchestrator,
  judge, apply layer, a payload extension, and two tools. No new task type.
- **Testing:** per user request, NO formal unit-test suite for 2b — smoke/manual verification
  only. Two safety rails are retained (not negotiable, they are recovery not tests): apply uses
  `git apply --3way` so conflicts surface instead of corrupting files; the snapshot ref is
  retained until the agent confirms, so the pre-apply state is recoverable.

### Reused as-is (already in the codebase)

- `atria/core/git/worktree.py` — `WorktreeManager(project_dir)` with `create(base_branch=…)`,
  `remove(name, force)`, `list()`. `create` runs `git worktree add -b <branch> <path> <base>`.
- `atria/core/tasks/*` — `TaskIQClient` (enqueue/await), `SubagentTaskPayload`, the worker that
  rebuilds a headless autonomous runtime and runs the subagent.
- `atria/core/blackboard/*` (Phase 2a) — `Blackboard`/`BlackboardHandle`, `PATCH_SUMMARY` notes,
  `render`, `archive`. `ToolExecutionContext.blackboard` field exists.

### DeLM reference

- `.references/DeLM/src/runners/swebench_orchestrator.py` — N-solver fan-out (semaphore +
  gather), start-stagger, winner = max reward, "all solvers failed" → fail row, per-thread cost
  aggregation. We replace the oracle reward with the LLM judge; "all failed" → no-acceptable-
  candidate.

## Goals / Non-goals

**Goals**
- `solve_parallel(task, n)` fans out N autonomous solvers, each in an isolated git worktree off
  a snapshot of the current (incl. uncommitted) state, each with the blackboard attached.
- `get_parallel_result(job_id)` awaits the solvers, extracts candidates (worktree diff +
  verified PATCH_SUMMARY), runs the LLM judge, applies the winner to the workspace, cleans up.
- Maximum reuse of Sub-project 1 + Phase 2a; the only task-layer change is extending the payload.
- Guaranteed cleanup (worktrees, snapshot, job record) and recoverable apply.

**Non-goals**
- Objective per-candidate test execution (judge trusts verified PATCH_SUMMARY evidence).
- Blocking/synchronous solve. A formal unit-test suite (smoke/manual only this phase).
- DeLM's per-thread cost/CSV bookkeeping and benchmark machinery.

## Architecture

A new `atria/core/parallel/` package + a payload/worker extension + two tools.

```
atria/core/parallel/
  snapshot.py      # snapshot_worktree(repo_dir)->base_ref (incl. uncommitted); discard_snapshot(ref)
  job_store.py     # JobStore(redis): save/load/delete  key atria:pjob:{job_id}, TTL
  candidate.py     # extract_candidate(worktree, base_ref, blackboard, thread_id)->Candidate
  judge.py         # judge_candidates(task, candidates)->JudgeResult{winner_index, reasoning}
  apply.py         # apply_diff(repo_dir, diff)->ApplyResult{ok, conflicted_files}
  orchestrator.py  # ParallelOrchestrator.start(...) / .collect(...)

reused: atria/core/git/worktree.py, atria/core/tasks/*, atria/core/blackboard/*
extended: atria/core/tasks/payload.py  (+ blackboard_task_id, + thread_id)
          worker run path              (attach Blackboard when blackboard_task_id set)
new tools: solve_parallel(task, n), get_parallel_result(job_id)
```

**Boundaries:** `snapshot`/`candidate`/`apply` are thin git wrappers (one responsibility each);
`judge` is one structured LLM call; `job_store` is Redis CRUD (injectable client, like
`meta.py`); `orchestrator` is the sole composer of the two-phase lifecycle. The fan-out is just
N existing background-subagent tasks.

## Components

### `snapshot.py`
- `snapshot_worktree(repo_dir) -> str`: if the tree is dirty, `git stash create` → returns that
  commit; else returns `HEAD`. The returned commit-ish includes committed + uncommitted state and
  is what worktrees fork from.
- `discard_snapshot(repo_dir, ref) -> None`: drop the temporary object if one was created.

### Payload extension + worker attach
- `SubagentTaskPayload` gains `blackboard_task_id: str | None = None` and `thread_id: int = 0`.
- The worker, when `blackboard_task_id` is set, builds `Blackboard(blackboard_task_id,
  thread_id=…)` + `BlackboardHandle` (Phase 2a) and sets it on the subagent run's
  `ToolExecutionContext.blackboard` — activating the `NOTE` tool + "Shared Lessons" injection.
  `working_dir` is the worktree path (already a payload field).

### `job_store.py`
- `JobStore(redis)`: `save(job_id, record)`, `load(job_id) -> record | None`, `delete(job_id)`.
  Key `atria:pjob:{job_id}`, TTL (config). Record: `{task_ids[], worktree_names[], worktree_paths[],
  blackboard_task_id, base_ref, repo_dir, n, task}`. Injectable redis client (caller-owned).

### `candidate.py`
- `Candidate{thread_id, diff, patch_summary, ok}`.
- `extract_candidate(worktree_path, base_ref, blackboard, thread_id) -> Candidate`:
  `diff = git diff <base_ref>` run in the worktree; `patch_summary` = the latest verified
  PATCH_SUMMARY note for `thread_id` from the blackboard (empty if none → `ok=False`).

### `judge.py`
- `JudgeResult{winner_index, reasoning}`.
- `judge_candidates(task, candidates) -> JudgeResult`: one LLM call (structured output) comparing
  each `(diff, PATCH_SUMMARY evidence/risk)` against the task; returns the best index, or
  `winner_index = -1` when none are acceptable (e.g. empty/failed candidates). Uses the project's
  existing LLM client.

### `apply.py`
- `ApplyResult{ok, conflicted_files}`.
- `apply_diff(repo_dir, diff) -> ApplyResult`: `git apply --3way` the winner's diff onto the user
  workspace; on conflicts, leave markers and report `conflicted_files` (do not force-revert).

### `orchestrator.py`
- `ParallelOrchestrator(task_client, worktree_manager, job_store, blackboard_factory, llm)`:
  - `start(task, n, repo_dir, owner_id, session_id) -> str` (job_id):
    clamp `n` to `[2, max_solvers]`; `base_ref = snapshot_worktree(repo_dir)`; create N worktrees
    off `base_ref`; `blackboard_task_id = new id`; for `i in range(n)` enqueue a background-subagent
    task (`task_client.enqueue`) with `prompt=task`, `working_dir=worktree[i]`, `blackboard_task_id`,
    `thread_id=i`, solver `subagent_type`; optional start-stagger; `job_store.save`; return `job_id`.
    On any failure mid-setup, remove created worktrees + `discard_snapshot` before raising.
  - `collect(job_id, block, timeout) -> dict`:
    `load`; await N results (`task_client.await_result`); if not all done → `{status:"running",
    done, n}`. Else, in a `try/finally` (finally = remove worktrees + discard snapshot + delete job):
    extract candidates from finished+successful solvers → `judge_candidates` → if `winner_index>=0`
    `apply_diff(repo_dir, winner.diff)` else skip → `blackboard.archive()` → return
    `{status:"done", winner_thread, applied, conflicted_files, reasoning, candidates:[…], dropped:[…]}`.

### Tools
- `solve_parallel(task: str, n: int = 3)` → `orchestrator.start(...)` → `{job_id, status:"running", n}`
  + guidance to call `get_parallel_result` later.
- `get_parallel_result(job_id: str, block?: bool, timeout?: int)` → `orchestrator.collect(...)`.
- Schemas in `definitions.py`; dispatch in `registry.py`; mirror Sub-project 1's
  `spawn_subagent`/`get_subagent_output`. The orchestrator is attached to the run like the task
  client is (server lifespan / per-run).

### Config
- A dedicated `ParallelConfig` (Pydantic, mirroring `TasksConfig`/`BlackboardConfig` in
  `atria/models/config.py`, attached to `AppConfig` as `parallel`): `max_solvers` (default 5),
  `default_solvers` (3), `solver_start_stagger_seconds` (default 0), `pjob_ttl` (default 3600),
  `redis_url` (default `redis://localhost:6379/0`).

## Data flow

**Phase 1 (`solve_parallel`):** snapshot → N worktrees off snapshot → enqueue N background
subagents (each: `working_dir`=worktree, `blackboard_task_id`, `thread_id`) → save job → return
`job_id`. Each solver (worker) attaches the blackboard, reads peers' verified notes, writes NOTEs,
emits a verified PATCH_SUMMARY before finishing; edits stay in its worktree.

**Phase 2 (`get_parallel_result`):** load job → await N results → running if incomplete → extract
candidates (diff + PATCH_SUMMARY) → judge → apply winner (`--3way`) → archive blackboard →
cleanup (worktrees + snapshot + job) → return summary.

## Error handling & edge cases

- **No acceptable candidate** (`winner_index == -1`, all failed, or no verified PATCH_SUMMARY) →
  apply nothing; `{status:"done", applied:false, reason:"no acceptable candidate", candidates}`.
  Worktrees still cleaned up. The agent can fall back to solving directly.
- **Partial solver failure** (Sub-project 1 surfaces `failed`/`orphaned`) → judge over the
  successful candidates only; list the dropped threads in the summary (no silent truncation).
- **Apply conflict** → `git apply --3way` reports `conflicted_files`; markers are left in place
  (not force-reverted); the result flags it; the snapshot ref is retained so the pre-apply state
  is recoverable.
- **Workspace moved since snapshot** → `--3way` resolves most drift; unresolvable hunks surface
  as conflicts.
- **Redis/worker down at enqueue** → `solve_parallel` returns `{error}`; created worktrees removed
  + snapshot discarded (no partial state left).
- **Guaranteed cleanup** → worktree/snapshot/job removal runs in `collect`'s `finally` even if
  judge/apply raises, so no leaked worktrees or refs.
- **Cost bounds** → `n` clamped to `[2, max_solvers]`; per-solver timeout inherits Sub-project 1.

## Testing

Per user request for this phase: **no formal unit-test suite** — smoke/manual verification only.
Retained safety rails (recovery, not tests): `git apply --3way` surfaces conflicts; the snapshot
ref is retained until the agent confirms.

**Smoke / manual (real, with `OPENAI_API_KEY` + Redis + worker):** in a real git repo, the agent
calls `solve_parallel` on a real task with `n=2`; confirm two worktrees run, share notes via the
blackboard, each emit a PATCH_SUMMARY, the judge picks one, its diff applies to the workspace, and
worktrees/snapshot are cleaned up. Also exercise the no-acceptable-candidate and apply-conflict
paths once by hand.

## Notes

- This is the only part of the DeLM port that mutates the user's real git workspace. The
  `--3way` apply + retained snapshot are deliberate guardrails given the reduced testing.
- Phase 2a's deferred lifecycle (FAIL-invalidation, selective unfold) can be layered into the
  blackboard renderer here if the N-solver digest proves too noisy.
