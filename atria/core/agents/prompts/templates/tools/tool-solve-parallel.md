<!--
name: 'Tool Description: solve_parallel'
description: Fan out N autonomous solvers on one task, each in an isolated worktree
version: 1.0.0
-->

Solve one task with N independent solvers running in parallel. Each solver runs as an autonomous background subagent in its own isolated git worktree (forked from a snapshot of the current working tree, including uncommitted changes) and shares verified notes with its peers via a shared blackboard.

Returns immediately with a `job_id`. Use `get_parallel_result(job_id)` to await the solvers, judge their candidate solutions, and apply the winner's diff to your workspace.

## Usage notes

- Use for non-trivial tasks where independent attempts are likely to differ in quality and a judge can pick the best (e.g. a bug fix with several plausible approaches). Overkill for trivial edits.
- `n` is clamped to `[2, max_solvers]` (config; default range 2–5, default 3 when omitted).
- Requires a running TaskIQ worker and Redis. If unavailable the tool returns an error.
- This only STARTS the solvers. Nothing is applied to your workspace until you call `get_parallel_result(job_id)`.
