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

- `data/stages/<topic>/<stage>.json` — one per pipeline stage
  (`research`, `outline`, `keypoints`, `tags`, `sources`, `score`, `render`,
  `assemble`, `verify`). Each stage reads the prior stage(s) and writes its
  own file, so the pipeline is resumable and inspectable.
- `data/briefings/<topic>.json` — written by the `assemble` stage: final
  briefing with `headline`, `key_points`, `reading_time_min`,
  `confidence` (0–1), `tags` (list), optional `sources`.
- `data/digest.json` — written by `merge`: totals, top topic, and the full
  ranking by `confidence * reading_time_min`.

Override the output dir with `ATRIA_TOPIC_BRIEFINGS_DIR`.

## How to use

Absolute paths. Let `<b>` = `python <modules>/topic_briefings/scripts/briefing.py`.

Run ONE pipeline stage for ONE topic (the atomic dispatchable unit):

```
<b> research --topic ai
<b> outline  --topic ai
<b> keypoints --topic ai
<b> tags     --topic ai
<b> sources  --topic ai
<b> score    --topic ai
<b> render   --topic ai
<b> assemble --topic ai
<b> verify   --topic ai
```

Merge every verified briefing into the digest (run AFTER all `verify`s):

```
<b> merge
```

Backward-compat shortcut — run the full 9-stage pipeline for one topic in
one process (useful for manual testing, NOT for dispatch):

```
<b> gen --topic ai
```

Inspect results:

```
<b> list
<b> show --topic ai
<b> reset
```

## Decomposition guidance (for divide)

When dispatched with `solve(strategy="divide")`, split the request into a
chained DAG per topic + one final merge. For each topic emit these 9
subtasks in order, each depending on the previous one:

- `id="research_<topic>"`, no `depends_on`, description =
  "Run `<b> research --topic <topic>`".
- `id="outline_<topic>"`, `depends_on=["research_<topic>"]`, description =
  "Run `<b> outline --topic <topic>`".
- `id="keypoints_<topic>"`, `depends_on=["research_<topic>"]`, description =
  "Run `<b> keypoints --topic <topic>`".
- `id="tags_<topic>"`, `depends_on=["research_<topic>"]`, description =
  "Run `<b> tags --topic <topic>`".
- `id="sources_<topic>"`, `depends_on=["research_<topic>"]`, description =
  "Run `<b> sources --topic <topic>`".
- `id="score_<topic>"`, `depends_on=["keypoints_<topic>"]`, description =
  "Run `<b> score --topic <topic>`".
- `id="render_<topic>"`,
  `depends_on=["outline_<topic>","keypoints_<topic>","tags_<topic>","sources_<topic>","score_<topic>"]`,
  description = "Run `<b> render --topic <topic>`".
- `id="assemble_<topic>"`, `depends_on=["render_<topic>"]`, description =
  "Run `<b> assemble --topic <topic>`".
- `id="verify_<topic>"`, `depends_on=["assemble_<topic>"]`, description =
  "Run `<b> verify --topic <topic>`".

Then one final task:

- `id="merge"`, `depends_on=[all verify_<topic> ids]`, description =
  "Run `<b> merge`".

Result: for N topics the DAG has **9N + 1** subtasks, giving the Dispatch
tab sustained visible progress instead of a two-shot flash. NEVER emit the
old single `gen_<topic>` task in a dispatched plan — that shortcut is only
for manual, single-process runs.

## Files

- `SKILL.md` — this overview.
- `scripts/briefing.py` — the CLI. Pipeline stages:
  `research`, `outline`, `keypoints`, `tags`, `sources`, `score`, `render`,
  `assemble`, `verify`. Aggregate/utility: `merge`, `gen` (shortcut), `list`,
  `show`, `dashboard`, `reset`.
- `data/stages/<topic>/` — per-stage intermediate JSON (auto-created; gitignored).
- `data/briefings/` + `data/digest.json` — final outputs (auto-created; gitignored).
