---
name: topic_briefings
description: Soạn executive briefing cho nhiều chủ đề (AI, biotech, climate, quantum, …) rồi tổng hợp thành weekly digest. Mỗi topic là một đơn vị công việc độc lập (`gen --topic`), bước `merge` phụ thuộc tất cả — fan-out + join lý tưởng cho solve(strategy="divide"). Non-coding scenario để demo dispatch tracking.
---

# topic_briefings

Generate a short executive briefing per **topic** (e.g. `ai`, `biotech`,
`climate`, `quantum`, `energy`, `space`, `chips`, `finance`), then **merge**
them into a weekly digest with a ranked reading order. Each per-topic briefing
is fully independent; the merge step depends on all of them — a classic
fan-out + join DAG. No LLM calls: content is deterministic synthetic prose
derived from the topic name (like `batch_reports`), so runs are reproducible
and fast to demo.

This module exists to demo **agent dispatch** on non-coding content: a
multi-topic request decomposes into one `gen` subtask per topic (all
parallelizable) plus a final `merge` that depends on them.

## When to use

ALWAYS DISPATCH. Any request to build briefings for this module (especially
the word "dispatch", or 2+ topics like "ai, biotech, climate, quantum rồi
tổng hợp") → dispatch as your first action:

```
solve(strategy="divide", module="topic_briefings", request="<the full request>")
```

Then collect with `get_solve_result(job_id)`. The orchestrator splits it into
independent `gen` subtasks + a dependent `merge`, fans them out to background
workers, and streams progress to the **Dispatch** tab.

Do NOT run `briefing.py` yourself with `run_command`, and do NOT use
`spawn_subagent`, for these requests — that is not dispatching. Only run a
single command inline if the user explicitly asks for just ONE topic, or if
`solve` returns an "unavailable" error.

## Data model

Plain JSON under `<modules>/topic_briefings/data/` (auto-created):

- `data/briefings/<topic>.json` — one per topic: `headline`, `key_points`
  (list of 3), `reading_time_min`, `confidence` (0–1), `tags` (list). All
  fields derived deterministically from the topic name.
- `data/digest.json` — written by `merge`: totals, top topic, and the full
  ranking by `confidence * reading_time_min`.

Override the output dir with `ATRIA_TOPIC_BRIEFINGS_DIR`.

## How to use

Absolute paths. Let `<b>` = `python <modules>/topic_briefings/scripts/briefing.py`.

Generate ONE topic's briefing (the independent, dispatchable unit):

```
<b> gen --topic ai
```

Merge every generated briefing into the digest (run AFTER all `gen`s):

```
<b> merge
```

Inspect results:

```
<b> list
<b> show --topic ai
<b> reset
```

## Decomposition guidance (for divide)

When dispatched with `solve(strategy="divide")`, split the request into
exactly:

- one task per topic: `id="gen_<topic>"`, no `depends_on`, description =
  "Run `python <modules>/topic_briefings/scripts/briefing.py gen --topic <topic>`".
- one final task: `id="merge"`, `depends_on=[all gen_* ids]`, description =
  "Run `python <modules>/topic_briefings/scripts/briefing.py merge`".

## Files

- `SKILL.md` — this overview.
- `scripts/briefing.py` — the CLI (`gen`, `merge`, `list`, `show`, `reset`, `dashboard`).
- `data/` — generated JSON briefings + digest (auto-created; gitignored).
