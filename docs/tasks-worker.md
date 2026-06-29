# Running background subagents (TaskIQ)

Background subagents require Redis plus two extra processes alongside the web server.

## 1. Redis
Reachable at the DEFAULT url `redis://localhost:6379/0`. NOTE (MVP): the task broker is the
module singleton constructed at import with the default URL. `tasks.redis_url` in config is
used for the orphan-tracking meta store and should match the broker's Redis. To use a
non-default Redis for the broker itself, run all processes against that Redis as the default.

## 2. Worker
    taskiq worker atria.core.tasks.broker:broker atria.core.tasks.tasks

## 3. Scheduler (orphan janitor)
    taskiq scheduler atria.core.tasks.scheduler:scheduler

## Config (.atria/settings.json)
    { "tasks": { "redis_url": "redis://localhost:6379/0",
                 "result_ttl": 3600, "orphan_after": 1800 } }

Without a worker running, `spawn_subagent(run_in_background=true)` enqueues but never
completes; `get_subagent_output` returns status `running` until `orphan_after`, then
`failed: orphaned`. With Redis down at startup, the client fails to start and background
subagents are disabled — `spawn_subagent(run_in_background=true)` falls back to synchronous
execution (graceful degradation).

Background subagents run FULLY AUTONOMOUS (auto-approve), because the worker has no
interactive approval/ask-user channel.
