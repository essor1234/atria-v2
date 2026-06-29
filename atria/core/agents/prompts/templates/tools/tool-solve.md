<!--
name: 'Tool Description: solve'
description: Dispatch work via a chosen strategy — divide (DAG decomposition) or parallel (worktree fan-out + judge)
version: 1.0.0
-->

Dispatch a complex task to autonomous background workers using one of two strategies. Returns immediately with a `job_id`; call `get_solve_result(job_id)` to collect.

Choose `strategy`:

- `strategy="divide"` — Decompose a `request` into a DAG of discrete sub-tasks and fan them out over the active module's workflow. Sub-tasks run as autonomous subagents coordinated by the orchestrator, respecting dependencies between them, and all results are aggregated. Use for work that splits into independent or sequential units (processing many items, running checks across a data set, a multi-step pipeline). Pass `request` (the work to decompose) and optionally `module` (defaults to the active module).

- `strategy="parallel"` — Run one `task` with N independent solvers in parallel. Each solver runs in its own isolated git worktree (forked from a snapshot of the current tree, including uncommitted changes) and shares verified notes via a shared blackboard. Use for non-trivial tasks where independent attempts differ in quality and a judge can pick the best (e.g. a bug fix with several plausible approaches); overkill for trivial edits. Pass `task` and optionally `n` (clamped to `[2, max_solvers]`; default 3).

## Usage notes

- Requires a running TaskIQ worker and Redis. If unavailable the tool returns an error.
- This only STARTS the work. Nothing is finalised (and for `parallel`, nothing is applied to your workspace) until you call `get_solve_result(job_id)`.
- For `divide`, `task` is accepted as an alias of `request`.
