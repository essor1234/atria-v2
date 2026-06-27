<!--
name: 'Tool Description: divide_work'
description: Decompose a complex request into sub-tasks and execute them via the divide-and-conquer orchestrator
version: 1.0.0
-->

Decompose a complex request into discrete sub-tasks and fan them out over the active module's workflow. Each sub-task runs as an autonomous background subagent coordinated by the DivideOrchestrator.

Returns immediately with a `job_id`. Use `get_divide_result(job_id)` to poll progress and collect the final aggregated result.

## Usage notes

- Use for requests that can be broken into independent or sequential work units (e.g. processing multiple items, running checks across a data set, executing a multi-step pipeline).
- `module` identifies which module's workflow definition governs decomposition. Defaults to the active module when omitted.
- Requires a running TaskIQ worker and Redis. If unavailable the tool returns an error.
- This only STARTS the job. Nothing is finalised until you call `get_divide_result(job_id)`.
