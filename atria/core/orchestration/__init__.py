"""Shared plumbing for the DeLM orchestrators (parallel solve + divide work).

`parallel` and `divide` previously each carried a byte-identical Redis ``JobStore`` and
an identical sync→async event-loop bridge. Those live here once now:
- ``job_store.JobStore`` — prefix-namespaced job-record CRUD.
- ``bridge`` — ``make_run_async`` (reuse the task client's loop) + ``ensure_async_redis``.
"""
