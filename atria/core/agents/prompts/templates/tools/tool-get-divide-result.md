<!--
name: 'Tool Description: get_divide_result'
description: Poll or await the result of a divide_work job
version: 1.0.0
-->

Collect the result of a `divide_work` job. Awaits completion of all sub-tasks; once done, returns the aggregated output produced by the DivideOrchestrator.

## Usage notes

- `job_id` is the value returned by `divide_work`.
- By default blocks until all sub-tasks complete. Use `block=false` for a non-blocking status check (returns `status: running` with a progress count while tasks are still working).
- Returns `status: unknown` when the job ID is not found in the job store.
