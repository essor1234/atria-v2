# Item Flow Tracking Module — Design

**Date:** 2026-06-26
**Status:** Approved (design), pending implementation plan
**Module name:** `item_flow_tracking`

## 1. Purpose

A new filesystem-backed module that tracks laundry orders through a fixed
processing pipeline. Each order belongs to a customer (identified by **phone
number**), is split into one or more **parts ("lots")** at intake, and each part
flows through a fixed sequence of steps while occupying shared physical
resources (bins, washers, dryers, fold/count areas). The module ships an
embedded SQLite store, a subcommand CLI, lazy-loaded sub-skills, and a
dashboard.

This follows the existing `modules/warehouse/` pattern exactly: `SKILL.md` +
`manifest.json` + `scripts/_db.py` (embedded SQLite) + `scripts/<cli>.py`
(argparse subcommands) + `skills/*.md` (on-demand sub-skills) + `dashboard.html`.

## 2. Domain model

### Business reality
- A workshop has a **fixed pool of physical resources**, reused across orders:
  default **15 bins ("Bin"), 10 washers, 10 dryers, 1 fold area, 1 count area**
  (counts configurable).
- A customer's order is poured into N bins at intake → N parts. Each part is the
  unit of tracking.
- A part moves between resources: a Bin's contents go into a washer, come out
  into any free Bin, go into a dryer, etc. The physical bin/machine number
  changes as it moves; the **logical part keeps a stable ID for its whole life**.
- Resources are constrained, so the dashboard must show what is busy/free and
  which order occupies it.

### Fixed steps (ordered)
`nhận hàng → giặt → sấy → gấp → kiểm đếm → giao hàng → xong`
plus a **làm lại (redo)** transition that sends a part back to an earlier step
(default: `giặt`), setting `is_redo` and logging an event.

Internal step keys: `nhan_hang`, `giat`, `say`, `gap`, `kiem_dem`, `giao_hang`,
`done`.

### Step ↔ resource kind mapping
The step is **auto-inferred from the resource** a part is moved into:
- washer → `giat`
- dryer → `say`
- fold → `gap`
- count → `kiem_dem`
- bin → step unchanged (part is "waiting" / parked in a bin)

This matches the described flow ("bin 1 → wash area 1 → bin 3 → dry area 3"):
moving a part into a machine advances it; parking it in a bin is just a
relocation.

### Order completion rule
At `kiểm đếm`, each part's item count is entered individually; the system sums
them into `orders.total_items`. An order may only advance to `giao hàng` / `xong`
once **all** its parts have been counted.

## 3. Data model (SQLite)

Schema lives in `scripts/_db.py`, bootstrapped on first `connect()` and seeded
with the default resource pool (mirrors `warehouse/scripts/_db.py`). Provides
`connect()`, `connect_readonly()`, `now()`, `db_path()` (env override
`ATRIA_FLOW_DB` for tests), `log_event(...)`, row→dict normalizers, and `seed()`.

### `orders`
- `order_id` TEXT PK — format `DH-YYYYMMDD-NNN`
- `customer_phone` TEXT NOT NULL — customer identity
- `customer_name` TEXT
- `status` TEXT — `active` | `done` | `cancelled`
- `total_items` INTEGER — finalized sum after counting (NULL until counted)
- `note` TEXT
- `created_at`, `updated_at` TEXT (ISO-8601 Z)

### `lots` (parts)
- `lot_id` TEXT PK — format `DH-YYYYMMDD-NNN-P1`
- `order_id` TEXT NOT NULL → `orders.order_id`
- `label` TEXT — `P1`, `P2`, …
- `step` TEXT — current step key
- `current_resource` TEXT NULL → `resources.resource_id` (where it physically is)
- `item_count` INTEGER NULL — this part's counted quantity
- `is_redo` INTEGER DEFAULT 0
- `status` TEXT — `active` | `done`
- `created_at`, `updated_at` TEXT

### `resources` (fixed pool)
- `resource_id` TEXT PK — `bin-1`, `washer-1`, `dryer-1`, `fold-1`, `count-1`
- `kind` TEXT — `bin` | `washer` | `dryer` | `fold` | `count`
- `label` TEXT — display, e.g. "Bin 1", "Máy giặt 1"
- `status` TEXT — `free` | `busy` | `maintenance`
- Default seed: 15 bins, 10 washers, 10 dryers, 1 fold, 1 count.
- Capacity = 1 part each; occupancy derived from `lots.current_resource`.

### `lot_events` (audit ledger — the trace source)
- `id` INTEGER PK AUTOINCREMENT
- `lot_id` TEXT NOT NULL
- `order_id` TEXT NOT NULL (denormalized)
- `event_type` TEXT — `intake` | `move` | `redo` | `count` | `deliver` | …
- `from_step`, `to_step` TEXT NULL
- `from_resource`, `to_resource` TEXT NULL
- `item_count` INTEGER NULL
- `timestamp` TEXT NOT NULL
- `notes` TEXT NULL
- Index on `(order_id, timestamp)` and `(lot_id, timestamp)`.

## 4. Operations — CLI `scripts/flow.py`

Argparse subcommands dispatched via `set_defaults(fn=...)`, matching
`inventory.py`. Every command accepts `--json` for machine-readable output used
by the dashboard and the agent.

### Mutating
- `order new --phone <p> [--name <n>] --bins <N> [--note <s>]`
  → create order + N parts, auto-assign N free bins, step = `nhan_hang`,
  mark bins busy, log `intake` events. Errors if fewer than N free bins exist.
- `lot move --lot <lot_id> --to <resource_id> [--force]`
  → free old resource, occupy new resource, infer new step from resource kind
  (bin keeps step), log `move`. Error if target busy unless `--force`.
- `lot count --lot <lot_id> --items <n>`
  → set part `item_count`, recompute `orders.total_items`, log `count`.
- `lot redo --lot <lot_id> [--to <step>] [--notes <s>]`
  → set `is_redo=1`, move step back (default `giat`), log `redo`.
- `lot deliver --lot <lot_id>` / `order deliver --order <order_id>`
  → mark delivered/done (order requires all parts counted), free resources,
  log `deliver`.
- `order cancel --order <order_id> [--reason <s>]` → status `cancelled`, free resources.

### Read-only
- `order list [--status <s>] [--phone <p>]`
- `order show --order <order_id>` (order + parts + per-part current step/resource)
- `customer history --phone <p>` (all orders for a phone, newest first)
- `resource list [--kind <k>] [--status <s>]`
- `resource set --resource <id> --status <free|busy|maintenance>` (manual override)
- `dashboard --json` → single payload feeding `dashboard.html` (resources,
  active orders + parts, WIP-by-step buckets).

### Resource configuration (data-management sub-skill)
- `resource add --kind <k> --count <n>` / `resource retire --resource <id>`
  to adjust the pool beyond defaults.

## 5. Dashboard — `dashboard.html`

Loads data from `flow.py dashboard --json` (served the same way
`warehouse/dashboard.html` loads its data). Three regions:

1. **Resources** — visual grid of 15 bins / 10 washers / 10 dryers / fold /
   count, colored by status (free/busy/maintenance); busy cells show which
   order/part occupy them.
2. **Active orders** — list per order: customer phone, its parts with a per-part
   step progress bar, and running total counted.
3. **By-step board (kanban)** — columns = steps, cards = parts currently at that
   step, so WIP per stage is visible at a glance.

`manifest.json` provides `display_name`, `dashboard` config (title, height,
badge_color), and `activity` labels (default + per-subcommand running/done) for
Simple Mode.

## 6. File structure

```
modules/item_flow_tracking/
├── SKILL.md                 # overview, when-to-use, data model, sub-skill pointers
├── manifest.json            # display_name, dashboard cfg, activity labels
├── icon.svg
├── dashboard.html
├── scripts/
│   ├── _db.py               # schema + connect/seed/helpers
│   └── flow.py              # CLI subcommands
├── skills/                  # lazy-loaded via invoke_skill()
│   ├── tracking-ops.md      # order new, lot move, redo, count, deliver
│   ├── analytics.md         # WIP by step, throughput, customer history, resource load
│   └── data-management.md   # export/import CSV, reset, configure resources
└── data/                    # flow.db auto-created (gitignored)
```

## 7. Testing

- Unit tests `tests/test_item_flow_tracking.py` using `ATRIA_FLOW_DB` pointed at
  a tmp file: schema bootstrap + seed; `order new` assigns bins and creates
  parts; `lot move` infers step, frees/occupies resources, rejects busy target;
  `lot count` sums to order total; order cannot deliver until all parts counted;
  `redo` sets flag and moves step back; `lot_events` ledger records transitions.
- End-to-end: register the module, run the CLI against a real flow, and confirm
  `dashboard --json` returns the expected shape (per project testing rules:
  unit tests **and** real end-to-end run).

## 8. Decisions locked

- Tracking unit = logical **part (lot)** with a stable ID; bins/machines are
  reusable resources it occupies, not identities.
- Step auto-inferred from resource kind; parking in a bin keeps the step.
- Counting is per-part, summed to the order; no physical bin-merge modeling.
- Redo default target = `giặt`.
- Resource pool defaults 15/10/10/1/1, configurable; capacity 1 part each.

## 9. Out of scope (YAGNI)

- Physical bin merge/split operations.
- Pricing/billing, payments, SMS notifications.
- Multi-workshop / multi-tenant resource pools.
- Auth/permissions (inherits host app).
