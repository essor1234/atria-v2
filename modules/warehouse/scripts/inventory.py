#!/usr/bin/env python
"""SQLite-backed inventory management for the warehouse module.

The live store is a single ``warehouse.db`` file (see ``_db.py``). Every stock
change is recorded in an append-only ``movements`` ledger alongside the
current-state ``items`` table.

Subcommands:
  state ........ list, summary, low-stock, valuation, history, query
  CRUD ......... add, update, remove, reset
  stock ops .... adjust, receive, ship, move, set-reorder
  data ......... export, import, migrate
"""

from __future__ import annotations

import argparse
import csv
import io
import json as _json
import sqlite3
import sys
from pathlib import Path

import _db

# ── small output helpers ────────────────────────────────────────────────────


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _emit(obj: object) -> None:
    print(_json.dumps(obj))


def _find(conn: sqlite3.Connection, sku: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE sku = ?", (sku,)).fetchone()


def _low_stock_skus(items: list[dict]) -> list[str]:
    return [it["sku"] for it in items if it["quantity"] <= it["reorder_level"]]


_SORT_COLUMNS = {
    "sku": "sku COLLATE NOCASE",
    "name": "name COLLATE NOCASE",
    "quantity": "quantity DESC",
    "value": "(quantity * unit_price) DESC",
    "updated": "updated_at DESC",
}


# ── read commands ───────────────────────────────────────────────────────────


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[object] = []
    if args.query:
        where.append("(sku LIKE ? OR name LIKE ?)")
        like = f"%{args.query}%"
        params += [like, like]
    if args.location:
        where.append("location LIKE ?")
        params.append(f"%{args.location}%")
    if args.min_price is not None:
        where.append("unit_price >= ?")
        params.append(args.min_price)
    if args.max_price is not None:
        where.append("unit_price <= ?")
        params.append(args.max_price)

    sql = "SELECT * FROM items"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + _SORT_COLUMNS.get(args.sort, _SORT_COLUMNS["sku"])

    rows = [_db.item_dict(r) for r in conn.execute(sql, params).fetchall()]
    if args.low_only:
        rows = [r for r in rows if r["quantity"] <= r["reorder_level"]]
    low = _low_stock_skus(rows)

    if args.json:
        _emit({"items": rows, "low_stock": low})
        return 0

    _print_table(rows)
    if low:
        print(f"\nlow stock (<= reorder_level): {', '.join(low)}")
    return 0


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no items)")
        return
    fields = _db.ITEM_FIELDS
    text = [{f: str(r.get(f, "")) for f in fields} for r in rows]
    widths = {f: max(len(f), max((len(r[f]) for r in text), default=0)) for f in fields}
    print("  ".join(f.ljust(widths[f]) for f in fields))
    print("  ".join("-" * widths[f] for f in fields))
    for r in text:
        print("  ".join(r[f].ljust(widths[f]) for f in fields))


def cmd_low_stock(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = [_db.item_dict(r) for r in conn.execute("SELECT * FROM items").fetchall()]
    low = [r for r in rows if r["quantity"] <= r["reorder_level"]]
    if args.json:
        _emit({"items": low, "low_stock": [r["sku"] for r in low]})
        return 0
    _print_table(low)
    return 0


def cmd_summary(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = [_db.item_dict(r) for r in conn.execute("SELECT * FROM items").fetchall()]
    total_units = sum(r["quantity"] for r in rows)
    total_value = round(sum(r["quantity"] * r["unit_price"] for r in rows), 2)
    low = _low_stock_skus(rows)
    by_loc: dict[str, dict] = {}
    for r in rows:
        loc = r["location"] or "(none)"
        agg = by_loc.setdefault(loc, {"location": loc, "skus": 0, "units": 0, "value": 0.0})
        agg["skus"] += 1
        agg["units"] += r["quantity"]
        agg["value"] = round(agg["value"] + r["quantity"] * r["unit_price"], 2)
    summary = {
        "skus": len(rows),
        "units": total_units,
        "value": total_value,
        "low_stock_count": len(low),
        "low_stock": low,
        "by_location": sorted(by_loc.values(), key=lambda a: a["location"]),
    }
    if args.json:
        _emit(summary)
        return 0
    print(f"SKUs:            {summary['skus']}")
    print(f"Units on hand:   {summary['units']}")
    print(f"Inventory value: ${summary['value']:.2f}")
    print(f"Low stock:       {summary['low_stock_count']}"
          + (f" ({', '.join(low)})" if low else ""))
    print("\nBy location:")
    for a in summary["by_location"]:
        print(f"  {a['location']:<10} {a['skus']:>3} skus  {a['units']:>6} units  ${a['value']:.2f}")
    return 0


def cmd_valuation(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = [_db.item_dict(r) for r in conn.execute("SELECT * FROM items").fetchall()]
    groups: dict[str, dict] = {}
    for r in rows:
        key = (r["location"] or "(none)") if args.by == "location" else r["sku"]
        agg = groups.setdefault(key, {"key": key, "units": 0, "value": 0.0})
        agg["units"] += r["quantity"]
        agg["value"] = round(agg["value"] + r["quantity"] * r["unit_price"], 2)
    out = sorted(groups.values(), key=lambda a: a["value"], reverse=True)
    if args.json:
        _emit({"by": args.by, "groups": out})
        return 0
    label = "Location" if args.by == "location" else "SKU"
    print(f"{label:<12} {'Units':>8} {'Value':>12}")
    for a in out:
        print(f"{a['key']:<12} {a['units']:>8} {'$' + format(a['value'], '.2f'):>12}")
    return 0


def cmd_history(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    sql = "SELECT * FROM movements"
    params: list[object] = []
    if args.sku:
        sql += " WHERE sku = ?"
        params.append(args.sku)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(args.limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    if args.json:
        _emit({"movements": rows})
        return 0
    if not rows:
        print("(no movements)")
        return 0
    for m in rows:
        sign = f"{m['delta']:+d}" if m["delta"] else "0"
        extra = " ".join(filter(None, [
            f"-> {m['balance']}" if m["balance"] is not None else "",
            f"({m['reason']})" if m["reason"] else "",
            f"ref={m['reference']}" if m["reference"] else "",
        ]))
        print(f"{m['created_at']}  {m['sku']:<10} {m['kind']:<11} {sign:>5}  {extra}")
    return 0


def cmd_query(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    # conn here is the read-only connection (see main()).
    rows = [dict(r) for r in conn.execute(args.sql).fetchall()]
    if args.json:
        _emit({"rows": rows})
        return 0
    if not rows:
        print("(no rows)")
        return 0
    cols = list(rows[0].keys())
    text = [{c: str(r.get(c, "")) for c in cols} for r in rows]
    widths = {c: max(len(c), max((len(r[c]) for r in text), default=0)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in text:
        print("  ".join(r[c].ljust(widths[c]) for c in cols))
    return 0


# ── write commands ───────────────────────────────────────────────────────────


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if _find(conn, args.sku):
        _err(f"SKU already exists: {args.sku}")
        return 1
    ts = _db.now()
    conn.execute(
        "INSERT INTO items "
        "(sku, name, location, quantity, unit_price, reorder_level, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (args.sku, args.name, args.location, args.quantity,
         args.unit_price, args.reorder_level, ts, ts),
    )
    _db.log_movement(conn, args.sku, "add", args.quantity, args.quantity,
                     reason="created", commit=False)
    conn.commit()
    print(f"added: {args.sku}")
    return 0


def cmd_update(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find(conn, args.sku)
    if row is None:
        _err(f"SKU not found: {args.sku}")
        return 1
    sets: list[str] = []
    params: list[object] = []
    qty_delta = 0
    new_balance = row["quantity"]
    for field, value in [("name", args.name), ("location", args.location),
                         ("unit_price", args.unit_price), ("reorder_level", args.reorder_level)]:
        if value is not None:
            sets.append(f"{field} = ?")
            params.append(value)
    if args.quantity is not None:
        qty_delta = args.quantity - row["quantity"]
        new_balance = args.quantity
        sets.append("quantity = ?")
        params.append(args.quantity)
    if not sets:
        _err("nothing to update (pass at least one field)")
        return 1
    sets.append("updated_at = ?")
    params.append(_db.now())
    params.append(args.sku)
    conn.execute(f"UPDATE items SET {', '.join(sets)} WHERE sku = ?", params)
    if qty_delta:
        _db.log_movement(conn, args.sku, "recount", qty_delta, new_balance,
                         reason="manual update", commit=False)
    conn.commit()
    print(f"updated: {args.sku}")
    return 0


def _apply_delta(conn: sqlite3.Connection, sku: str, delta: int, kind: str,
                 reason: str | None, reference: str | None) -> int:
    row = _find(conn, sku)
    if row is None:
        _err(f"SKU not found: {sku}")
        return 1
    new_qty = row["quantity"] + delta
    if new_qty < 0:
        _err(f"would go negative ({new_qty}) for {sku}")
        return 1
    conn.execute("UPDATE items SET quantity = ?, updated_at = ? WHERE sku = ?",
                 (new_qty, _db.now(), sku))
    _db.log_movement(conn, sku, kind, delta, new_qty,
                     reason=reason, reference=reference, commit=False)
    conn.commit()
    print(f"{kind}: {sku} -> quantity={new_qty}")
    return 0


def cmd_adjust(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    return _apply_delta(conn, args.sku, args.delta, "adjust", args.reason, args.reference)


def cmd_receive(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    return _apply_delta(conn, args.sku, abs(args.qty), "receive", args.reason, args.reference)


def cmd_ship(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    return _apply_delta(conn, args.sku, -abs(args.qty), "ship", args.reason, args.reference)


def cmd_move(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find(conn, args.sku)
    if row is None:
        _err(f"SKU not found: {args.sku}")
        return 1
    conn.execute("UPDATE items SET location = ?, updated_at = ? WHERE sku = ?",
                 (args.location, _db.now(), args.sku))
    _db.log_movement(conn, args.sku, "move", 0, row["quantity"],
                     reason=f"{row['location'] or '(none)'} -> {args.location}", commit=False)
    conn.commit()
    print(f"moved: {args.sku} -> {args.location}")
    return 0


def cmd_set_reorder(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find(conn, args.sku)
    if row is None:
        _err(f"SKU not found: {args.sku}")
        return 1
    conn.execute("UPDATE items SET reorder_level = ?, updated_at = ? WHERE sku = ?",
                 (args.level, _db.now(), args.sku))
    _db.log_movement(conn, args.sku, "set-reorder", 0, row["quantity"],
                     reason=f"reorder_level -> {args.level}", commit=False)
    conn.commit()
    print(f"set-reorder: {args.sku} -> {args.level}")
    return 0


def cmd_remove(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find(conn, args.sku)
    if row is None:
        _err(f"SKU not found: {args.sku}")
        return 1
    conn.execute("DELETE FROM items WHERE sku = ?", (args.sku,))
    _db.log_movement(conn, args.sku, "remove", -row["quantity"], 0,
                     reason="deleted", commit=False)
    conn.commit()
    print(f"removed: {args.sku}")
    return 0


def cmd_reset(conn: sqlite3.Connection, _args: argparse.Namespace) -> int:
    conn.execute("DELETE FROM items")
    conn.execute("DELETE FROM movements")
    conn.commit()
    print(f"reset: {_db.db_path()}")
    return 0


# ── data import / export ──────────────────────────────────────────────────────


def cmd_export(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.table == "movements":
        rows = [dict(r) for r in conn.execute("SELECT * FROM movements ORDER BY id").fetchall()]
        cols = ["id", "sku", "kind", "delta", "balance", "reason", "reference", "created_at"]
    else:
        rows = [_db.item_dict(r) for r in
                conn.execute("SELECT * FROM items ORDER BY sku").fetchall()]
        cols = _db.ITEM_FIELDS

    if args.format == "json":
        payload = _json.dumps({args.table: rows}, indent=2)
    else:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow({c: r.get(c, "") for c in cols})
        payload = buf.getvalue()

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"exported {len(rows)} {args.table} row(s) -> {args.out}")
    else:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def cmd_import(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        _err(f"file not found: {args.file}")
        return 1
    text = path.read_text(encoding="utf-8")
    if args.format == "json":
        data = _json.loads(text)
        rows = data.get("items", data) if isinstance(data, dict) else data
    else:
        rows = list(csv.DictReader(io.StringIO(text)))

    if args.replace:
        conn.execute("DELETE FROM items")
        conn.commit()

    ts = _db.now()
    added = updated = 0
    for r in rows:
        try:
            sku = r["sku"]
            qty = int(r["quantity"])
            price = float(r["unit_price"])
            reorder = int(r["reorder_level"])
        except (KeyError, ValueError, TypeError):
            continue
        existing = _find(conn, sku)
        if existing is None:
            conn.execute(
                "INSERT INTO items "
                "(sku, name, location, quantity, unit_price, reorder_level, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sku, r.get("name", sku), (r.get("location") or ""), qty, price, reorder, ts, ts),
            )
            _db.log_movement(conn, sku, "add", qty, qty, reason="import", commit=False)
            added += 1
        else:
            delta = qty - existing["quantity"]
            conn.execute(
                "UPDATE items SET name = ?, location = ?, quantity = ?, "
                "unit_price = ?, reorder_level = ?, updated_at = ? WHERE sku = ?",
                (r.get("name", existing["name"]), (r.get("location") or existing["location"]),
                 qty, price, reorder, ts, sku),
            )
            if delta:
                _db.log_movement(conn, sku, "recount", delta, qty, reason="import", commit=False)
            updated += 1
    conn.commit()
    print(f"imported: {added} added, {updated} updated")
    return 0


def cmd_migrate(conn: sqlite3.Connection, _args: argparse.Namespace) -> int:
    if not _db.LEGACY_CSV.exists():
        print(f"no legacy CSV to migrate at {_db.LEGACY_CSV}")
        return 0
    inserted = _db.seed(conn)
    print(f"migrated {inserted} item(s) from {_db.LEGACY_CSV.name}")
    return 0


# ── argument parsing / dispatch ──────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warehouse inventory (SQLite-backed).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list items with optional filters")
    p.add_argument("--query", help="substring filter on sku/name")
    p.add_argument("--location", help="substring filter on location")
    p.add_argument("--low-only", action="store_true", help="only items at/below reorder level")
    p.add_argument("--min-price", type=float)
    p.add_argument("--max-price", type=float)
    p.add_argument("--sort", choices=sorted(_SORT_COLUMNS), default="sku")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("low-stock", help="list items at or below reorder level")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_low_stock)

    p = sub.add_parser("summary", help="aggregate KPIs (counts, units, value, low stock)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("valuation", help="inventory value grouped by location or sku")
    p.add_argument("--by", choices=["location", "sku"], default="location")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_valuation)

    p = sub.add_parser("history", help="movement ledger (newest first)")
    p.add_argument("--sku", help="restrict to one SKU")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_history)

    p = sub.add_parser("query", help="run a read-only SELECT against the DB")
    p.add_argument("--sql", required=True, help="a single SELECT/WITH statement")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("add", help="add a new item")
    p.add_argument("--sku", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--location", required=True)
    p.add_argument("--quantity", type=int, required=True)
    p.add_argument("--unit-price", type=float, required=True)
    p.add_argument("--reorder-level", type=int, required=True)
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("update", help="patch fields on an existing item")
    p.add_argument("--sku", required=True)
    p.add_argument("--name")
    p.add_argument("--location")
    p.add_argument("--quantity", type=int)
    p.add_argument("--unit-price", type=float)
    p.add_argument("--reorder-level", type=int)
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("adjust", help="add a delta to quantity")
    p.add_argument("--sku", required=True)
    p.add_argument("--delta", type=int, required=True)
    p.add_argument("--reason")
    p.add_argument("--reference")
    p.set_defaults(fn=cmd_adjust)

    p = sub.add_parser("receive", help="receive stock (positive movement)")
    p.add_argument("--sku", required=True)
    p.add_argument("--qty", type=int, required=True)
    p.add_argument("--reason")
    p.add_argument("--reference")
    p.set_defaults(fn=cmd_receive)

    p = sub.add_parser("ship", help="ship stock (negative movement)")
    p.add_argument("--sku", required=True)
    p.add_argument("--qty", type=int, required=True)
    p.add_argument("--reason")
    p.add_argument("--reference")
    p.set_defaults(fn=cmd_ship)

    p = sub.add_parser("move", help="change an item's location")
    p.add_argument("--sku", required=True)
    p.add_argument("--location", required=True)
    p.set_defaults(fn=cmd_move)

    p = sub.add_parser("set-reorder", help="set an item's reorder level")
    p.add_argument("--sku", required=True)
    p.add_argument("--level", type=int, required=True)
    p.set_defaults(fn=cmd_set_reorder)

    p = sub.add_parser("remove", help="delete an item")
    p.add_argument("--sku", required=True)
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("reset", help="empty the items and movements tables")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("export", help="dump items or movements to csv/json")
    p.add_argument("--table", choices=["items", "movements"], default="items")
    p.add_argument("--format", choices=["csv", "json"], default="json")
    p.add_argument("--out", help="write to this path instead of stdout")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("import", help="bulk load items from csv/json")
    p.add_argument("--file", required=True)
    p.add_argument("--format", choices=["csv", "json"], default="csv")
    p.add_argument("--replace", action="store_true", help="clear items before importing")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("migrate", help="one-shot import from the legacy inventory.csv")
    p.set_defaults(fn=cmd_migrate)

    return parser


def _validate_query(sql: str) -> str | None:
    """Return an error string if ``sql`` is not a safe single read-only statement."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return "empty query"
    if ";" in stripped:
        return "only a single statement is allowed"
    head = stripped.lstrip("(").lstrip().split(None, 1)[0].lower()
    if head not in ("select", "with"):
        return "only SELECT / WITH queries are allowed"
    return None


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])

    if args.cmd == "query":
        problem = _validate_query(args.sql)
        if problem:
            _err(problem)
            return 1
        conn = _db.connect_readonly()
        try:
            return args.fn(conn, args)
        except sqlite3.Error as exc:
            _err(f"query failed: {exc}")
            return 1
        finally:
            conn.close()

    conn = _db.connect()
    try:
        return args.fn(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
