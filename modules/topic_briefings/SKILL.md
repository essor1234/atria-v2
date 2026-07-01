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

**ALWAYS DISPATCH. No inline execution — ever.** Every request touching this
module, including a single topic, must go through the dispatch pipeline as
your first action:

```
solve(strategy="divide", module="topic_briefings", request="<the full request>")
```

Then acknowledge the user briefly ("đã giao task, sẽ báo khi xong") and end
your turn. Do NOT call `get_solve_result` in the same turn — the system
notifies you when the job finishes.

For a single topic, the orchestrator still routes through the DAG (one `gen`
task) so the user sees live progress on the **Dispatch** tab. That
visibility is the whole point of this module.

Do NOT run `briefing.py` yourself with `run_command`. Do NOT use
`spawn_subagent`. Do NOT wait for the job. The only exception is if `solve`
returns an "unavailable" error — then fall back to `strategy="direct"` and
tell the user why.

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
