<!--
name: 'Tool Description: get_parallel_result'
description: Await parallel solvers, judge candidates, and apply the winner
version: 1.0.0
-->

Collect the result of a `solve_parallel` job. Awaits all solvers; once every solver has finished, extracts each candidate (its worktree diff + verified PATCH_SUMMARY), runs an LLM judge to pick the best, and applies the winner's diff to your workspace with a 3-way merge.

## Usage notes

- `job_id` is the value returned by `solve_parallel` (NOT a subagent tool_call_id).
- By default blocks until all solvers complete. Use `block=false` for a non-blocking status check (returns `status: running` with a done count while solvers are still working).
- When a winner is chosen, its diff is applied. On merge conflicts the conflict markers are left in place (never reverted) and the conflicting files are reported — the snapshot ref is retained so the work is recoverable.
- Returns `applied: false` with `winner_thread: -1` when no candidate is acceptable (empty diff or no real evidence).
- The snapshot the solvers forked from is retained for recovery and reported as `snapshot_ref`.
