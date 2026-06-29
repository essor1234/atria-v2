# Item Accounting & Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extend the `item_flow_tracking` module so orders carry per-item-type declared quantities at intake, counted quantities at `kiểm đếm`, and a per-customer reconciliation report (owed / extra / by type). Replaces per-lot counting with per-item-type order-level counting.

**Architecture:** Add an `order_items` table; `order new` declares lines, `order count` records counted-per-type, `report reconcile` aggregates declared-vs-counted per customer. Lots/bins keep physical location+step tracking unchanged. Spec: `docs/superpowers/specs/2026-06-27-item-flow-item-accounting-design.md`.

**Tech Stack:** Python stdlib (`sqlite3`, `argparse`), vanilla JS dashboard, pytest (subprocess).

## Global Constraints

- Module: `modules/item_flow_tracking/`. Python stdlib only; line length 100; type hints; Google docstrings.
- DB env override: `ATRIA_FLOW_DB`. Bump `SCHEMA_VERSION` to 2; migrate existing DBs in place (no data loss).
- `order_items`: `(order_id, item_type)` unique, `item_type` `COLLATE NOCASE`; `declared_qty ≥ 1`; `counted_qty` NULL until counted (≥ 0).
- `orders.total_items` = SUM(counted_qty) over lines (NULL until any counted); `orders.declared_total` = SUM(declared_qty).
- `--item` value format: `TYPE:QTY` (split on the LAST `:`). Reject empty type / non-int / qty < 1.
- Commits OMIT any `Co-Authored-By: Claude` trailer.
- Test cadence: do NOT run pytest per-task; batch to the final task (Task 8).
- **Kasa acceptance (keep these passing in Task 8 e2e):** C-01 ("100 khăn" → order, 100 khăn, có số đơn), C-02 (50 áo), C-05 ("200 khăn và 50 ga" → 2 lines), C-06 (reject negative qty), C-09 (`order new` returns order_id), Q-04 (`order show` → khách), Q-05 (`order show` → số món), plus the new reconcile owed/extra-by-type report.

---

### Task 1: `_db.py` — order_items table, declared_total, migration, helpers

**Files:** Modify `modules/item_flow_tracking/scripts/_db.py`

**Interfaces produced (used by later tasks):**
- `order_items` table + `orders.declared_total` column; `SCHEMA_VERSION = 2`.
- `recompute_order_totals(conn, order_id) -> None`
- `order_item_dict(row) -> dict` → `{item_type, declared_qty, counted_qty, diff}`
- `order_dict` now includes `declared_total`.

- [ ] **Step 1: Bump version + extend schema.** In `_db.py` set `SCHEMA_VERSION = 2`. Add `declared_total INTEGER` to the `orders` CREATE TABLE (after `total_items`). Append these to `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id     TEXT NOT NULL,
    item_type    TEXT NOT NULL COLLATE NOCASE,
    declared_qty INTEGER NOT NULL,
    counted_qty  INTEGER,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE (order_id, item_type)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
```

- [ ] **Step 2: Migration for existing DBs.** Add a helper and call it in `connect()` after `conn.executescript(_SCHEMA)` and before the seed/commit:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns missing from pre-v2 databases (idempotent)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if "declared_total" not in cols:
        conn.execute("ALTER TABLE orders ADD COLUMN declared_total INTEGER")
```

In `connect()`, add `_migrate(conn)` right after the `executescript`/`user_version` block.

- [ ] **Step 3: Helpers.** Add to `_db.py`:

```python
def recompute_order_totals(conn: sqlite3.Connection, order_id: str) -> None:
    """Recompute an order's declared_total and total_items from its item lines."""
    row = conn.execute(
        "SELECT SUM(declared_qty) AS dq, COUNT(counted_qty) AS cc, "
        "SUM(counted_qty) AS cq FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    declared = row["dq"]
    total = row["cq"] if row["cc"] else None
    conn.execute(
        "UPDATE orders SET declared_total = ?, total_items = ?, updated_at = ? "
        "WHERE order_id = ?",
        (declared, total, now(), order_id),
    )


def order_item_dict(row: sqlite3.Row) -> dict:
    """Normalise an ``order_items`` row into JSON shape (with declared/counted diff)."""
    declared = int(row["declared_qty"])
    counted = row["counted_qty"]
    return {
        "item_type": row["item_type"],
        "declared_qty": declared,
        "counted_qty": (int(counted) if counted is not None else None),
        "diff": (int(counted) - declared if counted is not None else None),
    }
```

- [ ] **Step 4: Include `declared_total` in `order_dict`.** In `order_dict`, add after `total_items`:

```python
        "declared_total": row["declared_total"],
```

- [ ] **Step 5: Commit.**

```bash
git add modules/item_flow_tracking/scripts/_db.py
git commit -m "feat(item-flow): order_items table, declared_total, v2 migration"
```

---

### Task 2: `order new --item` — declared item lines

**Files:** Modify `modules/item_flow_tracking/scripts/flow.py`

**Interfaces produced:** `_parse_item(spec)`, `_order_items(conn, order_id)`; `order new` accepts repeatable `--item TYPE:QTY`.

- [ ] **Step 1: Add parse + fetch helpers** (near the other helpers, after `_gen_order_id`):

```python
def _parse_item(spec: str) -> tuple[str | None, int | None, str | None]:
    """Parse a ``TYPE:QTY`` item spec. Returns (type, qty, error)."""
    if ":" not in spec:
        return None, None, "expected format TYPE:QTY"
    type_part, qty_part = spec.rsplit(":", 1)
    item_type = type_part.strip()
    if not item_type:
        return None, None, "empty item type"
    try:
        qty = int(qty_part.strip())
    except ValueError:
        return None, None, f"invalid quantity: {qty_part.strip()}"
    if qty < 1:
        return None, None, "quantity must be >= 1"
    return item_type, qty, None


def _order_items(conn: sqlite3.Connection, order_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    ).fetchall()
    return [_db.order_item_dict(r) for r in rows]
```

- [ ] **Step 2: Validate items BEFORE creating the order, then insert lines.** In `cmd_order_new`, immediately after the `args.bins < 1` check, parse items into a summed dict (case-insensitive key, first-seen casing) and bail on any error before any INSERT:

```python
    parsed: dict[str, int] = {}
    labels: dict[str, str] = {}
    for spec in (args.items or []):
        it, qty, err = _parse_item(spec)
        if err:
            _err(f"--item '{spec}': {err}")
            return 1
        key = it.lower()
        parsed[key] = parsed.get(key, 0) + qty
        labels.setdefault(key, it)
```

Then, after the lots loop and before the final `conn.commit()`, insert the item lines and recompute totals:

```python
    for key, qty in parsed.items():
        conn.execute(
            "INSERT INTO order_items (order_id, item_type, declared_qty, counted_qty, "
            "created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
            (order_id, labels[key], qty, ts, ts),
        )
    if parsed:
        _db.recompute_order_totals(conn, order_id)
```

Finally include items in the result payload — change the JSON emit to add items:

```python
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, order_id)),
               "lots": lots, "items": _order_items(conn, order_id)})
```

(Re-fetch the order via `_db.order_dict(_find_order(conn, order_id))` so `declared_total` is current; keep the human-readable branch as-is.)

- [ ] **Step 3: Register `--item`.** In `_build_parser`, on the `order new` subparser, add:

```python
    p.add_argument("--item", action="append", dest="items", default=None,
                   metavar="TYPE:QTY", help="declared item line, repeatable, e.g. --item khăn:100")
```

- [ ] **Step 4: Commit.**

```bash
git add modules/item_flow_tracking/scripts/flow.py
git commit -m "feat(item-flow): order new --item declares per-type quantities"
```

---

### Task 3: `order count --type` + remove `lot count`

**Files:** Modify `modules/item_flow_tracking/scripts/flow.py`

**Interfaces produced:** `order count --order --type --counted`; `lot count` removed.

- [ ] **Step 1: Add `cmd_order_count`** (place near `cmd_order_show`):

```python
def cmd_order_count(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    order = _find_order(conn, args.order)
    if not order:
        _err(f"order not found: {args.order}")
        return 1
    if args.counted < 0:
        _err("--counted must be >= 0")
        return 1
    row = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? AND item_type = ? COLLATE NOCASE",
        (args.order, args.type),
    ).fetchone()
    if not row:
        _err(f"order {args.order} has no item type: {args.type}")
        return 1
    ts = _db.now()
    conn.execute("UPDATE order_items SET counted_qty = ?, updated_at = ? WHERE id = ?",
                 (args.counted, ts, row["id"]))
    _db.recompute_order_totals(conn, args.order)
    _db.log_event(conn, "-", args.order, "count",
                  item_count=args.counted, notes=row["item_type"], commit=False)
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, args.order)),
               "items": _order_items(conn, args.order)})
    else:
        o = _find_order(conn, args.order)
        print(f"{args.order} · {row['item_type']} counted {args.counted} "
              f"— order total = {o['total_items']}")
    return 0
```

- [ ] **Step 2: Remove `lot count`.** Delete `cmd_lot_count` and the old `_recompute_order_total` helper (it was only used by `cmd_lot_count`). In `_build_parser`, delete the `lot.add_parser("count", …)` block. Add the `order count` subparser under the `order` group (after `show`):

```python
    p = order.add_parser("count", help="record counted quantity for an item type")
    p.add_argument("--order", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--counted", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_count)
```

- [ ] **Step 3: Commit.**

```bash
git add modules/item_flow_tracking/scripts/flow.py
git commit -m "feat(item-flow): order count per item type; remove per-lot count"
```

---

### Task 4: `order show` items + delivery gate by counted lines

**Files:** Modify `modules/item_flow_tracking/scripts/flow.py`

- [ ] **Step 1: `order show` includes items.** In `cmd_order_show`, after setting `order["lots"]`, add `order["items"] = _order_items(conn, args.order)`. In the human branch, after the lots loop, print each item line:

```python
        for it in order["items"]:
            cnt = "—" if it["counted_qty"] is None else it["counted_qty"]
            print(f"  {it['item_type']:<12} khai {it['declared_qty']:<5} đếm {cnt}")
```

- [ ] **Step 2: Delivery gate by item lines.** In `cmd_order_deliver`, replace the per-lot `uncounted` check with an item-line check:

```python
    items = conn.execute("SELECT * FROM order_items WHERE order_id = ?", (args.order,)).fetchall()
    uncounted = [r["item_type"] for r in items if r["counted_qty"] is None]
    if not items or uncounted:
        detail = ", ".join(uncounted) if uncounted else "(chưa có dòng hàng để đếm)"
        _err(f"cannot deliver — chưa đếm hết: {detail}")
        return 1
```

(Keep the rest of `cmd_order_deliver` — freeing resources, marking lots done, order done — unchanged.)

- [ ] **Step 3: `_maybe_complete_order` requires counted lines.** Replace `_maybe_complete_order` so it completes the order only when all lots are done AND all item lines are counted:

```python
def _maybe_complete_order(conn: sqlite3.Connection, order_id: str) -> None:
    lot = conn.execute(
        "SELECT COUNT(*) AS n, SUM(status = 'done') AS done FROM lots WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if not (lot["n"] and lot["done"] == lot["n"]):
        return
    it = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(counted_qty) AS c FROM order_items WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if it["n"] and it["c"] == it["n"]:
        conn.execute("UPDATE orders SET status = 'done', updated_at = ? WHERE order_id = ?",
                     (_db.now(), order_id))
```

- [ ] **Step 4: Commit.**

```bash
git add modules/item_flow_tracking/scripts/flow.py
git commit -m "feat(item-flow): order show item lines; deliver gated on counted types"
```

---

### Task 5: `report reconcile`

**Files:** Modify `modules/item_flow_tracking/scripts/flow.py`

- [ ] **Step 1: Add `cmd_report_reconcile`:**

```python
def cmd_report_reconcile(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where = ["o.status != 'cancelled'"]
    params: list[object] = []
    if args.phone:
        where.append("o.customer_phone = ?")
        params.append(args.phone)
    sql = (
        "SELECT o.customer_phone AS phone, oi.item_type AS item_type, "
        "SUM(oi.declared_qty) AS declared, COALESCE(SUM(oi.counted_qty), 0) AS counted "
        "FROM order_items oi JOIN orders o ON o.order_id = oi.order_id "
        "WHERE " + " AND ".join(where) +
        " GROUP BY o.customer_phone, oi.item_type COLLATE NOCASE "
        "ORDER BY o.customer_phone, oi.item_type"
    )
    customers: dict[str, dict] = {}
    for r in conn.execute(sql, params).fetchall():
        c = customers.setdefault(r["phone"], {
            "customer_phone": r["phone"], "items": [], "owed_total": 0, "extra_total": 0})
        declared, counted = int(r["declared"]), int(r["counted"])
        owed, extra = max(0, declared - counted), max(0, counted - declared)
        c["items"].append({"item_type": r["item_type"], "declared": declared,
                           "counted": counted, "owed": owed, "extra": extra})
        c["owed_total"] += owed
        c["extra_total"] += extra
    result = list(customers.values())
    if args.json:
        _emit({"customers": result})
    else:
        for c in result:
            print(f"{c['customer_phone']}  nợ {c['owed_total']} · thừa {c['extra_total']}")
            for it in c["items"]:
                print(f"  {it['item_type']:<12} khai {it['declared']:<5} "
                      f"đếm {it['counted']:<5} nợ {it['owed']} thừa {it['extra']}")
    return 0
```

- [ ] **Step 2: Register the `report` group** in `_build_parser` (before `return parser`):

```python
    report = sub.add_parser("report", help="reporting").add_subparsers(
        dest="cmd", required=True)
    p = report.add_parser("reconcile", help="declared vs counted per customer + type")
    p.add_argument("--phone", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_report_reconcile)
```

- [ ] **Step 3: Commit.**

```bash
git add modules/item_flow_tracking/scripts/flow.py
git commit -m "feat(item-flow): report reconcile (declared vs counted per customer)"
```

---

### Task 6: Dashboard — order items + reconcile panel

**Files:** Modify `modules/item_flow_tracking/scripts/flow.py` (`cmd_dashboard`), `modules/item_flow_tracking/dashboard.html`

- [ ] **Step 1: Dashboard payload includes items.** In `cmd_dashboard`, where it builds each active order dict (`o = _db.order_dict(r)` then `o["lots"] = …`), also add:

```python
        o["items"] = _order_items(conn, r["order_id"])
```

- [ ] **Step 2: dashboard.html "Đối chiếu món" rendering.** In the orders render (`renderOrders`), after the parts chips, append a per-item line built with `textContent` only (no innerHTML). For each `lot`-independent `o.items` entry show `item_type`, `declared_qty`, and `counted_qty` (— if null), and when `counted_qty != null && counted_qty < declared_qty` add a class marking it owed (coral). Add CSS:

```css
    .items { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
    .iline { font-size: 11px; padding: 3px 8px; border-radius: 999px; border: 1px solid hsl(var(--hairline-soft)); font-family: 'JetBrains Mono', monospace; }
    .iline.owed { border-color: hsl(var(--st-redo) / 0.5); background: hsl(var(--st-redo-soft) / 0.5); color: hsl(var(--st-redo)); }
```

And in `renderOrders`, after appending `parts`:

```javascript
          var items = document.createElement("div");
          items.className = "items";
          (o.items || []).forEach(function (it) {
            var line = document.createElement("span");
            var counted = it.counted_qty == null ? "—" : it.counted_qty;
            var owed = it.counted_qty != null && it.counted_qty < it.declared_qty;
            line.className = "iline" + (owed ? " owed" : "");
            line.textContent = it.item_type + " " + (it.counted_qty == null ? "" : counted + "/") + it.declared_qty;
            items.appendChild(line);
          });
          if ((o.items || []).length) d.appendChild(items);
```

- [ ] **Step 3: Commit.**

```bash
git add modules/item_flow_tracking/scripts/flow.py modules/item_flow_tracking/dashboard.html
git commit -m "feat(item-flow): dashboard shows declared vs counted item lines"
```

---

### Task 7: Docs, manifest, agent guidance

**Files:** Modify `SKILL.md`, `skills/tracking-ops.md`, `skills/analytics.md`, `manifest.json`

- [ ] **Step 1: SKILL.md hot commands + intake rule.** In the "How to use" section, update the order-new example to include items and add count + reconcile; add an explicit intake rule. Use `<f>` = the script path shorthand already defined there:

```
<f> order new --phone 0901234567 --name "KS A" --bins 3 --item "khăn:100" --item "ga:50"
<f> order count --order DH-20260627-001 --type khăn --counted 98
<f> report reconcile --phone 0901234567
```

Add a line: "**Khi nhận đơn, luôn hỏi số lượng và loại hàng nếu khách chưa nói** — không tạo đơn rỗng, không tự điền số mặc định." Update the sub-skill bullet for `tracking-ops` to mention `order count` (not `lot count`).

- [ ] **Step 2: tracking-ops.md** — replace the "Count a part" section with order-level counting and document `--item` on intake and `report reconcile` (move detailed reference here). Remove any `lot count` reference.

- [ ] **Step 3: analytics.md** — add a `report reconcile [--phone …]` section describing the owed/extra-by-type output.

- [ ] **Step 4: manifest.json** — add a `report` action label to `activity.actions`:

```json
      "report":    { "running": "Đang đối chiếu…",       "done": "Đã đối chiếu" },
```

- [ ] **Step 5: Commit.**

```bash
git add modules/item_flow_tracking/SKILL.md modules/item_flow_tracking/skills/tracking-ops.md modules/item_flow_tracking/skills/analytics.md modules/item_flow_tracking/manifest.json
git commit -m "docs(item-flow): item accounting commands + intake quantity rule"
```

---

### Task 8: Tests + verification (batched)

**Files:** Modify `tests/test_item_flow_tracking.py`; verification only otherwise

- [ ] **Step 1: Remove obsolete per-lot count tests.** Delete `test_count_sums_to_order_total` and `test_lot_deliver_rejects_uncounted_lot`, and update `test_lot_deliver_completes_order_when_last` and `test_order_deliver_requires_all_counted` to the new model (declare items at intake, count by type, then deliver). Any test that called `lot count` must move to `order count`.

- [ ] **Step 2: Add accounting tests** (append):

```python
# ── item accounting + reconciliation ─────────────────────────────────────────


def test_order_new_declares_item_lines(env):
    p = run_json(env, "order", "new", "--phone", "0901234567", "--bins", "2",
                 "--item", "khăn:100", "--item", "ga:50")
    types = {i["item_type"]: i["declared_qty"] for i in p["items"]}
    assert types == {"khăn": 100, "ga": 50}
    assert p["order"]["declared_total"] == 150


def test_order_new_rejects_bad_item(env):
    r = run(env, "order", "new", "--phone", "0900000000", "--bins", "1",
            "--item", "khăn:-10", "--json")
    assert r.returncode != 0
    r2 = run(env, "order", "new", "--phone", "0900000000", "--bins", "1",
             "--item", "khăn:abc", "--json")
    assert r2.returncode != 0


def test_order_count_by_type_updates_total(env):
    new = run_json(env, "order", "new", "--phone", "0902223334", "--bins", "1",
                   "--item", "khăn:100", "--item", "ga:50")
    oid = new["order"]["order_id"]
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "98")
    shown = run_json(env, "order", "show", "--order", oid)
    assert shown["order"]["total_items"] == 98  # only khăn counted so far
    khan = next(i for i in shown["order"]["items"] if i["item_type"] == "khăn")
    assert khan["counted_qty"] == 98 and khan["diff"] == -2


def test_order_count_unknown_type_errors(env):
    oid = run_json(env, "order", "new", "--phone", "0902223335", "--bins", "1",
                   "--item", "khăn:10")["order"]["order_id"]
    r = run(env, "order", "count", "--order", oid, "--type", "áo", "--counted", "5", "--json")
    assert r.returncode != 0


def test_reconcile_owed_and_extra(env):
    o1 = run_json(env, "order", "new", "--phone", "0905550000", "--bins", "1",
                  "--item", "khăn:100")["order"]["order_id"]
    run_json(env, "order", "count", "--order", o1, "--type", "khăn", "--counted", "98")
    o2 = run_json(env, "order", "new", "--phone", "0905550000", "--bins", "1",
                  "--item", "ga:20")["order"]["order_id"]
    run_json(env, "order", "count", "--order", o2, "--type", "ga", "--counted", "22")
    rec = run_json(env, "report", "reconcile", "--phone", "0905550000")
    c = rec["customers"][0]
    by = {i["item_type"]: i for i in c["items"]}
    assert by["khăn"]["owed"] == 2 and by["khăn"]["extra"] == 0
    assert by["ga"]["extra"] == 2 and by["ga"]["owed"] == 0
    assert c["owed_total"] == 2 and c["extra_total"] == 2


def test_deliver_requires_all_types_counted(env):
    new = run_json(env, "order", "new", "--phone", "0907770000", "--bins", "1",
                   "--item", "khăn:100", "--item", "ga:50")
    oid = new["order"]["order_id"]
    blocked = run(env, "order", "deliver", "--order", oid, "--json")
    assert blocked.returncode != 0 and "chưa đếm" in blocked.stderr
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "100")
    run_json(env, "order", "count", "--order", oid, "--type", "ga", "--counted", "50")
    ok = run_json(env, "order", "deliver", "--order", oid)
    assert ok["order"]["status"] == "done"


def test_v2_migration_upgrades_v1_db(env, tmp_path):
    # Build a v1-shaped DB (no order_items / declared_total), then connect via the CLI.
    import sqlite3
    dbp = tmp_path / "v1.db"
    conn = sqlite3.connect(dbp)
    conn.executescript(
        "CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_phone TEXT NOT NULL, "
        "customer_name TEXT, status TEXT NOT NULL DEFAULT 'active', total_items INTEGER, "
        "note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO orders VALUES ('DH-OLD-001','0900000000',NULL,'active',NULL,NULL,"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');"
    )
    conn.commit(); conn.close()
    e = dict(env); e["ATRIA_FLOW_DB"] = str(dbp)
    listed = run_json(e, "order", "list")
    assert any(o["order_id"] == "DH-OLD-001" for o in listed["orders"])  # no data loss
    # order_items table now usable
    assert run(e, "order", "new", "--phone", "0901111111", "--bins", "1",
               "--item", "khăn:5", "--json").returncode == 0
```

- [ ] **Step 2b: Run the suite.** `uv run pytest tests/test_item_flow_tracking.py -v` → all pass. Fix causes until green.

- [ ] **Step 3: Lint.** `uv run ruff check modules/item_flow_tracking/ tests/test_item_flow_tracking.py` → clean. (Module scripts are outside `make check`'s scope, like warehouse — only fix ruff on these files.)

- [ ] **Step 4: Real e2e (Kasa acceptance).** Against a throwaway DB:

```bash
export ATRIA_FLOW_DB=/tmp/acct_e2e.db; rm -f "$ATRIA_FLOW_DB"
S=modules/item_flow_tracking/scripts/flow.py
# C-01 / C-05: intake with item types, returns order id (C-09)
J=$(python $S order new --phone 0901234567 --name "KS A" --bins 2 --item "khăn:200" --item "ga:50" --json)
OID=$(echo "$J" | python -c "import sys,json;print(json.load(sys.stdin)['order']['order_id'])")
# C-06: reject negative
python $S order new --phone 0900000000 --bins 1 --item "khăn:-5" --json; echo "neg exit=$?"
# Q-04 / Q-05: show customer + quantities
python $S order show --order "$OID" --json
# count + reconcile owed/extra
python $S order count --order "$OID" --type khăn --counted 198 --json >/dev/null
python $S order count --order "$OID" --type ga --counted 50 --json >/dev/null
python $S report reconcile --phone 0901234567 --json
python $S order deliver --order "$OID" --json
rm -f "$ATRIA_FLOW_DB"; unset ATRIA_FLOW_DB
```

Confirm: order id returned (C-09); negative rejected (C-06); `order show` has customer_phone/name + items with declared 200/50 (Q-04/Q-05); reconcile shows khăn owed 2; deliver succeeds after both counted. Capture outputs in the report.

- [ ] **Step 5: Commit.**

```bash
git add tests/test_item_flow_tracking.py
git commit -m "test(item-flow): item accounting + reconciliation + v2 migration"
```

---

## Self-Review

- Spec §3 data model (order_items, declared_total, migration) → Task 1. ✓
- §4 intake `--item` → Task 2; `order count` + remove `lot count` → Task 3; `order show` items + deliver gate + `_maybe_complete_order` → Task 4; `report reconcile` → Task 5. ✓
- §5 dashboard → Task 6. ✓
- §6 docs/manifest/agent guidance → Task 7. ✓
- §7 tests + e2e + Kasa acceptance → Task 8. ✓
- Type/name consistency: `recompute_order_totals`, `order_item_dict`, `_parse_item`, `_order_items`, `cmd_order_count`, `cmd_report_reconcile` defined before use; `lot count`/`cmd_lot_count`/`_recompute_order_total` fully removed (Task 3) and their tests removed (Task 8). Dashboard reads `o.items[].{item_type,declared_qty,counted_qty}` matching Task 6's `cmd_dashboard` payload.
- No placeholders; every code step shows complete code.
