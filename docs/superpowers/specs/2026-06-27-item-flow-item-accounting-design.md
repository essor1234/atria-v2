# Item Accounting & Reconciliation — Design

**Date:** 2026-06-27
**Status:** Approved (design), pending plan
**Module:** `item_flow_tracking` (extends the existing module)

## 1. Purpose

Capture **what** and **how many** items an order contains — by item type
(khăn / áo / ga …) — at intake ("nhận đơn"), then record the actual counted
quantity per type at the counting step ("kiểm đếm"), so the shop can
**reconcile declared vs counted per customer**: who we owe items to (nợ), who
has extra (thừa), and which item types. This is the Kasa-style order quantity
the existing module lacked.

This replaces the previous per-part (per-lot) single-number counting with
per-item-type counting at the order level. Physical lots/bins continue to track
location and step exactly as before — only the quantity accounting changes.

## 2. Decisions locked (from brainstorming)

- An order carries **multiple item lines** (item type + declared quantity).
- Declared quantity is entered at intake; counted quantity per type is entered
  at `kiểm đếm`. Both are kept so they can be **reconciled** (declared vs
  counted) per customer and per type.
- Counting moves from **per-lot** (`lot count`) to **per-item-type at order
  level** (`order count`). `lot count` is removed. Lots/bins remain physical
  location + step tracking only.
- Item type is **free text** (operator-entered, e.g. "khăn"), trimmed; grouped
  case-insensitively for reconciliation.
- Reconciliation is the source of a per-brand statistics report (owed / extra /
  by type).

## 3. Data model changes

### New table `order_items`
- `id` INTEGER PK AUTOINCREMENT
- `order_id` TEXT NOT NULL → `orders.order_id`
- `item_type` TEXT NOT NULL (trimmed, as entered)
- `declared_qty` INTEGER NOT NULL (≥ 1)
- `counted_qty` INTEGER NULL (set at counting; ≥ 0)
- `created_at`, `updated_at` TEXT
- Unique on `(order_id, item_type)` (case-insensitive via `COLLATE NOCASE` on
  `item_type`). Index on `order_id`.

### `orders` table
- Add `declared_total` INTEGER NULL — convenience = SUM(`declared_qty`) over the
  order's lines (recomputed on item changes).
- `total_items` stays, redefined as SUM(`counted_qty`) over the order's lines
  (recomputed on count; NULL until at least one line counted).

### `lots` table
- `item_count` column is **retained but unused** (no destructive migration);
  the `lot count` command and its writes are removed.

### Migration (`_db.connect`)
- Bump `SCHEMA_VERSION` to 2.
- `CREATE TABLE IF NOT EXISTS order_items …` (+ index).
- Add `orders.declared_total` via a guarded `ALTER TABLE` (check
  `PRAGMA table_info(orders)`; add column if missing) so existing local DBs
  upgrade in place.

## 4. CLI changes (`scripts/flow.py`)

### Intake — declared lines
- `order new --phone <p> --bins <N> [--name <n>] [--note <s>] --item "LOẠI:SL" [--item …]`
  - `--item` is repeatable; value format `<type>:<qty>` (split on the **last**
    `:`; `qty` a positive int). At least zero allowed (back-compat: an order
    with no `--item` simply has no declared lines yet — see §6 agent guidance,
    which tells the agent to ask).
  - Creates one `order_items` row per type; duplicate types in one command are
    summed. Sets `orders.declared_total`.

### Counting — per type
- `order count --order <id> --type <t> --counted <n>`
  - Requires the type to exist on the order (error otherwise). Sets
    `counted_qty`, recomputes `orders.total_items`. Logs a `count` event
    (`item_count = n`, `notes = type`).
- **Remove** the `lot count` subcommand and `cmd_lot_count`.

### Inspect
- `order show --order <id>` → includes an `items` array: `[{item_type,
  declared_qty, counted_qty, diff}]` where `diff = counted - declared` (null
  until counted), plus `declared_total` / `total_items`.

### Reconciliation report (new)
- `report reconcile [--phone <p>] [--json]`
  - Aggregates `order_items` across the customer's **non-cancelled** orders,
    grouped by `(customer_phone, item_type)`:
    - `declared` = SUM(declared_qty)
    - `counted` = SUM(counted_qty) (treating NULL as 0)
    - `owed` = max(0, declared − counted)  (we still owe / are short)
    - `extra` = max(0, counted − declared)
  - With `--phone`, one customer; without, all customers.
  - Output: per customer → per type rows + per-customer totals
    ("đang nợ X món, thừa Y món").

### Delivery gate
- `order deliver --order <id>` now requires **every `order_items` line counted**
  (`counted_qty` NOT NULL) instead of "all lots counted". Message names the
  uncounted types.
- `_maybe_complete_order` (used by `lot deliver`) only flips the order to `done`
  when all lots are done **and** all item lines are counted; otherwise the order
  stays `active` awaiting counting.

## 5. Dashboard (`dashboard.html`)

Add a **"Đối chiếu món"** panel: for each active order, a compact line per item
type — declared vs counted — with the still-owed amount highlighted (coral) when
`counted < declared`. Consumes the `items` array now present on each order in
`dashboard --json` (extend `cmd_dashboard` to include order items).

## 6. Agent guidance (`SKILL.md` + `skills/tracking-ops.md`)

- At intake, the agent must **ask for quantity and item type** when the user
  hasn't given them (no default quantities, no empty orders) — Kasa C-03/C-08.
- Document `order new --item "khăn:100" --item "ga:50"`, `order count --type … --counted …`,
  and `report reconcile --phone …` inline in `SKILL.md` (hot commands), with the
  full reference in `tracking-ops.md`; update `analytics.md` for the report.
- Update `manifest.json` activity: add a `report` group label.

## 7. Testing

- Unit tests (`tests/test_item_flow_tracking.py`, env `ATRIA_FLOW_DB`):
  - `order new --item` creates declared lines; `declared_total` correct;
    duplicate types summed; bad `--item` format / non-positive qty rejected.
  - `order count --type` sets counted, recomputes `total_items`; unknown type
    rejected.
  - `order show` returns items with diffs.
  - `report reconcile` math: declared/counted/owed/extra per type; `--phone`
    filter; cancelled orders excluded.
  - `order deliver` gated on all lines counted; `_maybe_complete_order` keeps
    order active until counted.
  - Migration: an existing v1 DB (no `declared_total`, no `order_items`) upgrades
    on connect without data loss.
  - Remove/replace the old `lot count` tests.
- Real CLI end-to-end: intake with two item types → count both → reconcile shows
  owed/extra → deliver succeeds only after all counted.

## 8. Out of scope (this iteration)

- Item-type master list / autocomplete (free text for now).
- Due dates, pricing, the broader Kasa auth/roles and voice tests.
- Per-bin (per-lot) quantity counting (intentionally replaced).
