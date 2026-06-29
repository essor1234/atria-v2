<!--
name: 'Tool Description: get_solve_result'
description: Collect the result of a solve job (divide or parallel)
version: 1.0.0
-->

Collect the result of a `solve` job. The job's strategy is inferred automatically from its `job_id`, so you do not normally pass `strategy`.

- For a **divide** job: awaits completion of all sub-tasks and returns the aggregated output produced by the orchestrator.

- For a **parallel** job: awaits all solvers; once every solver has finished, extracts each candidate (its worktree diff + verified PATCH_SUMMARY), runs an LLM judge to pick the best, and applies the winner's diff to your workspace with a 3-way merge.

## Usage notes

- `job_id` is the value returned by `solve` (NOT a subagent tool_call_id).
- By default blocks until the job completes. Use `block=false` for a non-blocking status check (returns `status: running` with a progress count while work is ongoing).
- Parallel only: when a winner is chosen its diff is applied; on merge conflicts the conflict markers are left in place (never reverted) and the conflicting files are reported, with the snapshot ref retained for recovery. Returns `applied: false` with `winner_thread: -1` when no candidate is acceptable.
- Returns `status: unknown` when the job ID is not found in the job store.
