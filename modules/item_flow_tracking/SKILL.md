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
on first use and seeded with the fixed resource pool. Four tables: `orders`
(one per customer order), `lots` (parts; the tracking unit), `resources` (the
fixed pool — default 15 bins, 10 washers, 10 dryers, 1 fold, 1 count), and
`lot_events` (audit ledger). The DB path can be overridden with `ATRIA_FLOW_DB`
(used by tests); the live DB is gitignored.

Fixed steps, in order: `nhan_hang → giat → say → gap → kiem_dem → giao_hang →
done`, plus a `redo` transition. Moving a part into a resource infers its step:
washer→giặt, dryer→sấy, fold→gấp, count→kiểm đếm; a bin is just a holding spot
and keeps the step. At kiểm đếm each part's count is summed into the order
total; an order can only be delivered once all parts are counted.

## How to use

Bash CWD is the chat workspace, not the modules root — use absolute paths.
Replace `<modules>` with the absolute modules root from the "Active Modules"
prompt section. All operations are subcommands of `scripts/flow.py`. Add
`--json` for machine-readable output.

Most common — create an order and list active orders:

```
python <modules>/item_flow_tracking/scripts/flow.py order new --phone 0901234567 --name "Khach A" --bins 3
python <modules>/item_flow_tracking/scripts/flow.py order list
```

## Sub-skills (load on demand)

For anything beyond `order new`/`order list`/`order show`, load the matching
sub-skill with `invoke_skill` — do not guess flags:

- `invoke_skill("item_flow_tracking:tracking-ops")` — `lot move`, `lot count`,
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
