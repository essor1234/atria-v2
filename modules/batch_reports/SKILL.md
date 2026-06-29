---
name: batch_reports
description: Tạo báo cáo doanh thu theo nhiều vùng rồi tổng hợp. Mỗi vùng là một đơn vị công việc độc lập (gen --region), bước merge phụ thuộc tất cả — workload kiểu fan-out lý tưởng để dispatch song song qua solve(strategy="divide").
---

# batch_reports

Generate a sales report for each of several **regions**, then **merge** them into
a ranked summary. Every region report is an independent unit of work, and the
merge step depends on all of them — a classic fan-out + join DAG.

This module exists to demonstrate **agent dispatch**: a multi-region request
decomposes into one `gen` subtask per region (which can all run in parallel) plus
a final `merge` subtask that depends on them.

## When to use

ALWAYS DISPATCH. Any request to generate/run reports for this module (especially the word
"dispatch", or 2+ regions like "north, south, east, west rồi tổng hợp") → you
MUST dispatch as your first action:

```
solve(strategy="divide", module="batch_reports", request="<the full request>")
```

Then collect with `get_solve_result(job_id)`. The orchestrator splits it into
independent `gen` subtasks + a dependent `merge`, fans them out to background
workers, and streams progress to the **Dispatch** tab.

Do NOT run `report.py` yourself with `run_command`, and do NOT use
`spawn_subagent`, for these requests — that is not dispatching. Only run a single
command inline if the user explicitly asks for just ONE region, or if `solve`
returns an "unavailable" error.

## Data model

Plain JSON files under `<modules>/batch_reports/data/` (auto-created):

- `data/reports/<region>.json` — one per region: `units`, `avg_price`,
  `return_rate`, `revenue`. Metrics are derived deterministically from the region
  name, so results are reproducible.
- `data/summary.json` — written by `merge`: totals, top region, and the full
  revenue ranking.

The output directory can be overridden with `ATRIA_BATCH_REPORTS_DIR`.

## How to use

Bash CWD is the chat workspace, not the modules root — use **absolute paths**.
All operations are subcommands of `scripts/report.py`. Add `--json` for
machine-readable output. Let `<r>` = `python <modules>/batch_reports/scripts/report.py`.

Generate ONE region's report (the independent, dispatchable unit):

```
<r> gen --region north
```

Merge every generated report into the ranked summary (run AFTER all `gen`s):

```
<r> merge
```

Inspect results:

```
<r> list
<r> show --region north
<r> reset
```

## Decomposition guidance (for divide)

When this module is dispatched with `solve(strategy="divide")`, split the request
into exactly:

- one task per region: `id="gen_<region>"`, no `depends_on`, description =
  "Run `python <modules>/batch_reports/scripts/report.py gen --region <region>`".
- one final task: `id="merge"`, `depends_on=[all gen_* ids]`, description =
  "Run `python <modules>/batch_reports/scripts/report.py merge`".

## Files

- `SKILL.md` — this overview.
- `scripts/report.py` — the CLI (`gen`, `merge`, `list`, `show`, `reset`).
- `data/` — generated JSON reports + summary (auto-created; gitignored).
