---
name: item_flow_tracking
description: Theo dõi đơn giặt là — mỗi đơn của một khách (định danh bằng số điện thoại) chia thành nhiều phần ("lot"/Bin) chạy qua chuỗi bước cố định trên pool tài nguyên dùng chung (bin, máy giặt, máy sấy, khu gấp/đếm), backed by SQLite, có dashboard.
---

# item_flow_tracking

Track laundry orders backed by a single embedded **SQLite** database
(`data/flow.db`). Each order belongs to a customer (identified by **phone
number**) and is split at intake into one or more **parts ("lots")** — one per
Bin. Each part moves through a fixed pipeline while occupying shared physical
resources; every move is recorded in an append-only `lot_events` ledger.

## When to use

- The user wants to create/intake a laundry order and split it into bins.
- The user wants to move a part to the next station (wash/dry/fold/count) or
  back it for redo ("làm lại").
- The user wants to record counted quantities, deliver, or cancel an order.
- The user asks where an order or part is, or for a customer's order history.
- The user wants resource status (which bins/machines are busy/free).

## Data model

SQLite DB at `<modules>/item_flow_tracking/data/flow.db`, created automatically
on first use and seeded with the fixed resource pool. Five tables: `orders`
(one per customer order), `order_items` (declared + counted quantity per item
type), `lots` (physical parts/bins; location + step tracking), `resources` (the
fixed pool — default 15 bins, 10 washers, 10 dryers, 1 fold, 1 count), and
`lot_events` (audit ledger). The DB path can be overridden with `ATRIA_FLOW_DB`
(used by tests); the live DB is gitignored.

Fixed steps, in order: `nhan_hang → giat → say → gap → kiem_dem → giao_hang →
done`, plus a `redo` transition. Moving a part into a resource infers its step:
washer→giặt, dryer→sấy, fold→gấp, count→kiểm đếm; a bin is just a holding spot
and keeps the step. Item quantities are tracked **per item type across the whole
order**: `order new --item` declares them, `order count --type … --counted …`
records the counted quantity, and `order deliver` requires every declared item
type to have been counted.

## How to use

Bash CWD is the chat workspace, not the modules root — use absolute paths.
Replace `<modules>` with the absolute modules root from the "Active Modules"
prompt section. All operations are subcommands of `scripts/flow.py`. Add
`--json` for machine-readable output.

The everyday commands are below — run them directly, no sub-skill needed. Let
`<f>` = `python <modules>/item_flow_tracking/scripts/flow.py`.

**Khi nhận đơn, luôn hỏi số lượng và loại hàng nếu khách chưa nói** — không tạo đơn rỗng, không tự điền số mặc định.

Create an order split into N bins/parts, declaring item lines at intake, and list orders:

```
<f> order new --phone 0901234567 --name "Khach A" --bins 3 --item "khăn:100" --item "ga:50"
<f> order list
```

Move a part to the next station. The step is inferred from the target
(`washer→giặt`, `dryer→sấy`, `fold→gấp`, `count→kiểm đếm`; a `bin` just parks
it). You can target a part by its lot id **or** by the bin it currently sits in
(`--from`), so "chuyển thùng 1 sang máy giặt 3" is one call:

```
<f> lot move --from bin-1 --to washer-3
<f> lot move --lot DH-20260626-001-P1 --to dryer-2
```

Record the counted quantity per item type for an order:

```
<f> order count --order DH-20260627-001 --type khăn --counted 98
```

Reconcile declared vs counted items (per customer, per type):

```
<f> report reconcile --phone 0901234567
```

## Sub-skills (load on demand)

The commands above cover the common flow. For the rest, load the matching
sub-skill with `invoke_skill` — do not guess flags:

- `invoke_skill("item_flow_tracking:tracking-ops")` — full `lot move`, `order count`
  (per-type counted qty), `--item TYPE:QTY` intake flags, `report reconcile`,
  `lot redo`, `lot deliver`, `order deliver`, `order cancel`.
- `invoke_skill("item_flow_tracking:analytics")` — `order show`,
  `customer history`, `resource list`, and the `dashboard` payload.
- `invoke_skill("item_flow_tracking:data-management")` — `data export`,
  `data reset`, `resource set`, `resource add`, `resource retire`.

## Files

- `SKILL.md` — this overview.
- `skills/*.md` — on-demand sub-skill guides (tracking-ops, analytics, data-management).
- `scripts/_db.py` — SQLite connection, schema, resource-pool seed, ledger helper.
- `scripts/flow.py` — the flow-tracking CLI (orders, lots, resources, dashboard).
- `dashboard.html` — resource grid, active orders, and by-step board.
- `data/flow.db` — live SQLite store (auto-created; gitignored).
