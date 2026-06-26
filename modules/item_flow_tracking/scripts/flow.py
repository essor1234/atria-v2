#!/usr/bin/env python
"""Item flow tracking CLI for the item_flow_tracking module.

Tracks laundry orders (one customer per phone number) split into parts
("lots") that flow through a fixed step pipeline over a shared pool of
physical resources. The live store is a single ``flow.db`` file (see
``_db.py``); every mutation is recorded in the append-only ``lot_events``
ledger.

Subcommands:
  order ..... new, list, show, deliver, cancel
  lot ....... move, count, redo, deliver
  customer .. history
  resource .. list, set, add, retire
  data ...... dashboard, export, reset
"""

from __future__ import annotations

import argparse
import csv
import io
import json as _json
import sqlite3
import sys

import _db


# ── small output helpers ────────────────────────────────────────────────────


def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def _emit(obj: object) -> None:
    print(_json.dumps(obj, ensure_ascii=False))


def _find_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()


def _find_lot(conn: sqlite3.Connection, lot_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM lots WHERE lot_id = ?", (lot_id,)).fetchone()


def _find_resource(conn: sqlite3.Connection, rid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM resources WHERE resource_id = ?", (rid,)).fetchone()


def _order_lots(conn: sqlite3.Connection, order_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM lots WHERE order_id = ? ORDER BY label", (order_id,)
    ).fetchall()
    return [_db.lot_dict(r) for r in rows]


def _gen_order_id(conn: sqlite3.Connection) -> str:
    """Generate the next per-day order id: ``DH-YYYYMMDD-NNN``."""
    day = _db.now()[:10].replace("-", "")
    prefix = f"DH-{day}"
    n = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE order_id LIKE ?", (prefix + "-%",)
    ).fetchone()[0]
    return f"{prefix}-{n + 1:03d}"


# ── order commands ──────────────────────────────────────────────────────────


def cmd_order_new(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.bins < 1:
        _err("--bins must be >= 1")
        return 1
    free_bins = conn.execute(
        "SELECT * FROM resources WHERE kind = 'bin' AND status = 'free' ORDER BY rowid"
    ).fetchall()
    if len(free_bins) < args.bins:
        _err(f"not enough free bins: need {args.bins}, have {len(free_bins)}")
        return 1

    ts = _db.now()
    order_id = _gen_order_id(conn)
    conn.execute(
        "INSERT INTO orders (order_id, customer_phone, customer_name, status, "
        "total_items, note, created_at, updated_at) "
        "VALUES (?, ?, ?, 'active', NULL, ?, ?, ?)",
        (order_id, args.phone, args.name, args.note, ts, ts),
    )
    for i in range(1, args.bins + 1):
        bin_row = free_bins[i - 1]
        lot_id = f"{order_id}-P{i}"
        conn.execute(
            "INSERT INTO lots (lot_id, order_id, label, step, current_resource, "
            "item_count, is_redo, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'nhan_hang', ?, NULL, 0, 'active', ?, ?)",
            (lot_id, order_id, f"P{i}", bin_row["resource_id"], ts, ts),
        )
        conn.execute(
            "UPDATE resources SET status = 'busy' WHERE resource_id = ?",
            (bin_row["resource_id"],),
        )
        _db.log_event(conn, lot_id, order_id, "intake",
                      to_step="nhan_hang", to_resource=bin_row["resource_id"], commit=False)
    conn.commit()

    order = _db.order_dict(_find_order(conn, order_id))
    lots = _order_lots(conn, order_id)
    if args.json:
        _emit({"order": order, "lots": lots})
    else:
        print(f"Created {order_id} for {args.phone} — {args.bins} parts "
              f"({', '.join(lot['current_resource'] for lot in lots)})")
    return 0


def cmd_order_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[object] = []
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    if args.phone:
        where.append("customer_phone LIKE ?")
        params.append(f"%{args.phone}%")
    sql = "SELECT * FROM orders"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC"

    orders = []
    for r in conn.execute(sql, params).fetchall():
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)
    if args.json:
        _emit({"orders": orders})
    else:
        for o in orders:
            print(f"{o['order_id']}  {o['customer_phone']:<12}  {o['status']:<9}  "
                  f"{len(o['lots'])} parts  total={o['total_items']}")
    return 0


def cmd_order_show(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    row = _find_order(conn, args.order)
    if not row:
        _err(f"order not found: {args.order}")
        return 1
    order = _db.order_dict(row)
    order["lots"] = _order_lots(conn, args.order)
    if args.json:
        _emit({"order": order})
    else:
        print(f"{order['order_id']}  {order['customer_phone']}  {order['status']}")
        for lot in order["lots"]:
            print(f"  {lot['label']}  {lot['step_label']:<12}  "
                  f"@ {lot['current_resource'] or '-'}  count={lot['item_count']}")
    return 0


# ── lot commands ────────────────────────────────────────────────────────────


def cmd_lot_move(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    if lot["status"] != "active":
        _err(f"lot is not active: {args.lot} ({lot['status']})")
        return 1
    target = _find_resource(conn, args.to)
    if not target:
        _err(f"resource not found: {args.to}")
        return 1

    old = lot["current_resource"]
    if target["status"] == "busy" and target["resource_id"] != old and not args.force:
        _err(f"resource busy: {args.to} (use --force to override)")
        return 1

    new_step = _db.RESOURCE_KIND_TO_STEP.get(target["kind"], lot["step"])
    ts = _db.now()
    if old and old != target["resource_id"]:
        conn.execute("UPDATE resources SET status = 'free' WHERE resource_id = ?", (old,))
    conn.execute("UPDATE resources SET status = 'busy' WHERE resource_id = ?",
                 (target["resource_id"],))
    conn.execute(
        "UPDATE lots SET step = ?, current_resource = ?, updated_at = ? WHERE lot_id = ?",
        (new_step, target["resource_id"], ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "move",
                  from_step=lot["step"], to_step=new_step,
                  from_resource=old, to_resource=target["resource_id"], commit=False)
    conn.commit()

    if args.json:
        _emit({"lot": _db.lot_dict(_find_lot(conn, args.lot))})
    else:
        print(f"{args.lot} → {target['label']} ({_db.STEP_LABELS.get(new_step, new_step)})")
    return 0


# ── parser + dispatch ───────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Item flow tracking CLI")
    sub = parser.add_subparsers(dest="group", required=True)

    order = sub.add_parser("order", help="order operations").add_subparsers(
        dest="cmd", required=True)

    p = order.add_parser("new", help="create an order split into N bins/parts")
    p.add_argument("--phone", required=True)
    p.add_argument("--name", default=None)
    p.add_argument("--bins", type=int, required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_new)

    p = order.add_parser("list", help="list orders")
    p.add_argument("--status", choices=["active", "done", "cancelled"], default=None)
    p.add_argument("--phone", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_list)

    p = order.add_parser("show", help="show one order and its parts")
    p.add_argument("--order", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_show)

    lot = sub.add_parser("lot", help="lot (part) operations").add_subparsers(
        dest="cmd", required=True)

    p = lot.add_parser("move", help="move a lot into a resource (step inferred)")
    p.add_argument("--lot", required=True)
    p.add_argument("--to", required=True, help="target resource_id, e.g. washer-3 or bin-5")
    p.add_argument("--force", action="store_true", help="override a busy target")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_move)

    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv[1:])
    conn = _db.connect()
    try:
        return args.fn(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
