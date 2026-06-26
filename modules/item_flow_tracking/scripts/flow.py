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


# ── module-level constants ──────────────────────────────────────────────────

_EXPORT_TABLES = {"orders": "orders", "lots": "lots",
                  "resources": "resources", "events": "lot_events"}


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


# ── order commands ──────────────────────────────────────────────────────────


def cmd_order_new(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.bins < 1:
        _err("--bins must be >= 1")
        return 1
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
    for key, qty in parsed.items():
        conn.execute(
            "INSERT INTO order_items (order_id, item_type, declared_qty, counted_qty, "
            "created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
            (order_id, labels[key], qty, ts, ts),
        )
    if parsed:
        _db.recompute_order_totals(conn, order_id)
    conn.commit()

    lots = _order_lots(conn, order_id)
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, order_id)),
               "lots": lots, "items": _order_items(conn, order_id)})
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


def cmd_order_deliver(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    order = _find_order(conn, args.order)
    if not order:
        _err(f"order not found: {args.order}")
        return 1
    lots = conn.execute("SELECT * FROM lots WHERE order_id = ?", (args.order,)).fetchall()
    uncounted = [lot["lot_id"] for lot in lots if lot["item_count"] is None]
    if uncounted:
        _err(f"cannot deliver — not all parts counted: {', '.join(uncounted)}")
        return 1
    ts = _db.now()
    for lot in lots:
        _free_lot_resource(conn, lot)
        conn.execute(
            "UPDATE lots SET step = 'done', status = 'done', current_resource = NULL, "
            "updated_at = ? WHERE lot_id = ?",
            (ts, lot["lot_id"]),
        )
        _db.log_event(conn, lot["lot_id"], args.order, "deliver",
                      from_step=lot["step"], to_step="done",
                      from_resource=lot["current_resource"], commit=False)
    conn.execute("UPDATE orders SET status = 'done', updated_at = ? WHERE order_id = ?",
                 (ts, args.order))
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, args.order))})
    else:
        print(f"{args.order} delivered ({len(lots)} parts)")
    return 0


def cmd_order_cancel(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    order = _find_order(conn, args.order)
    if not order:
        _err(f"order not found: {args.order}")
        return 1
    lots = conn.execute("SELECT * FROM lots WHERE order_id = ?", (args.order,)).fetchall()
    ts = _db.now()
    for lot in lots:
        _free_lot_resource(conn, lot)
        conn.execute(
            "UPDATE lots SET status = 'cancelled', current_resource = NULL, "
            "updated_at = ? WHERE lot_id = ?",
            (ts, lot["lot_id"]),
        )
        _db.log_event(conn, lot["lot_id"], args.order, "cancel", notes=args.reason, commit=False)
    conn.execute("UPDATE orders SET status = 'cancelled', updated_at = ? WHERE order_id = ?",
                 (ts, args.order))
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, args.order))})
    else:
        print(f"{args.order} cancelled")
    return 0


# ── lot commands ────────────────────────────────────────────────────────────


def cmd_lot_move(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    # Resolve the lot either by id (--lot) or by the resource it sits in (--from).
    if args.from_resource:
        rows = conn.execute(
            "SELECT * FROM lots WHERE current_resource = ? AND status = 'active'",
            (args.from_resource,),
        ).fetchall()
        if not rows:
            _err(f"no active lot in resource: {args.from_resource}")
            return 1
        if len(rows) > 1:
            ids = ", ".join(r["lot_id"] for r in rows)
            _err(f"multiple active lots in {args.from_resource}: {ids} — use --lot")
            return 1
        lot = rows[0]
    else:
        lot = _find_lot(conn, args.lot)
        if not lot:
            _err(f"lot not found: {args.lot}")
            return 1
    lot_id = lot["lot_id"]
    if lot["status"] != "active":
        _err(f"lot is not active: {lot_id} ({lot['status']})")
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
        (new_step, target["resource_id"], ts, lot_id),
    )
    _db.log_event(conn, lot_id, lot["order_id"], "move",
                  from_step=lot["step"], to_step=new_step,
                  from_resource=old, to_resource=target["resource_id"], commit=False)
    conn.commit()

    if args.json:
        _emit({"lot": _db.lot_dict(_find_lot(conn, lot_id))})
    else:
        print(f"{lot_id} → {target['label']} ({_db.STEP_LABELS.get(new_step, new_step)})")
    return 0


def _recompute_order_total(conn: sqlite3.Connection, order_id: str) -> int | None:
    row = conn.execute(
        "SELECT COUNT(item_count) AS counted, SUM(item_count) AS total "
        "FROM lots WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    total = row["total"] if row["counted"] else None
    conn.execute(
        "UPDATE orders SET total_items = ?, updated_at = ? WHERE order_id = ?",
        (total, _db.now(), order_id),
    )
    return total


def _free_lot_resource(conn: sqlite3.Connection, lot: sqlite3.Row) -> None:
    if lot["current_resource"]:
        conn.execute("UPDATE resources SET status = 'free' WHERE resource_id = ?",
                     (lot["current_resource"],))


def _maybe_complete_order(conn: sqlite3.Connection, order_id: str) -> None:
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(status = 'done') AS done FROM lots WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if row["n"] and row["done"] == row["n"]:
        conn.execute("UPDATE orders SET status = 'done', updated_at = ? WHERE order_id = ?",
                     (_db.now(), order_id))


def cmd_lot_count(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    if args.items < 0:
        _err("--items must be >= 0")
        return 1
    ts = _db.now()
    conn.execute(
        "UPDATE lots SET item_count = ?, updated_at = ? WHERE lot_id = ?",
        (args.items, ts, args.lot),
    )
    _recompute_order_total(conn, lot["order_id"])
    _db.log_event(conn, args.lot, lot["order_id"], "count",
                  item_count=args.items, commit=False)
    conn.commit()

    if args.json:
        _emit({
            "lot": _db.lot_dict(_find_lot(conn, args.lot)),
            "order": _db.order_dict(_find_order(conn, lot["order_id"])),
        })
    else:
        order = _find_order(conn, lot["order_id"])
        print(f"{args.lot} counted {args.items} — order total = {order['total_items']}")
    return 0


def cmd_lot_redo(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    target = args.to or "giat"
    if target not in _db.STEPS:
        _err(f"unknown step: {target}")
        return 1
    ts = _db.now()
    conn.execute(
        "UPDATE lots SET step = ?, is_redo = 1, updated_at = ? WHERE lot_id = ?",
        (target, ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "redo",
                  from_step=lot["step"], to_step=target, notes=args.notes, commit=False)
    conn.commit()

    if args.json:
        _emit({"lot": _db.lot_dict(_find_lot(conn, args.lot))})
    else:
        print(f"{args.lot} sent back to {_db.STEP_LABELS.get(target, target)} (redo)")
    return 0


def cmd_lot_deliver(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    lot = _find_lot(conn, args.lot)
    if not lot:
        _err(f"lot not found: {args.lot}")
        return 1
    if lot["item_count"] is None:
        _err(f"cannot deliver — part not counted yet: {args.lot}")
        return 1
    ts = _db.now()
    _free_lot_resource(conn, lot)
    conn.execute(
        "UPDATE lots SET step = 'done', status = 'done', current_resource = NULL, "
        "updated_at = ? WHERE lot_id = ?",
        (ts, args.lot),
    )
    _db.log_event(conn, args.lot, lot["order_id"], "deliver",
                  from_step=lot["step"], to_step="done",
                  from_resource=lot["current_resource"], commit=False)
    _maybe_complete_order(conn, lot["order_id"])
    conn.commit()
    if args.json:
        _emit({"order": _db.order_dict(_find_order(conn, lot["order_id"]))})
    else:
        print(f"{args.lot} delivered")
    return 0


# ── customer + resource + dashboard commands ────────────────────────────────


def _resource_occupant(conn: sqlite3.Connection, rid: str) -> dict | None:
    row = conn.execute(
        "SELECT lot_id, order_id FROM lots WHERE current_resource = ? AND status = 'active'",
        (rid,),
    ).fetchone()
    return {"lot_id": row["lot_id"], "order_id": row["order_id"]} if row else None


def cmd_customer_history(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = conn.execute(
        "SELECT * FROM orders WHERE customer_phone = ? ORDER BY created_at DESC",
        (args.phone,),
    ).fetchall()
    orders = []
    for r in rows:
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)
    if args.json:
        _emit({"phone": args.phone, "orders": orders})
    else:
        print(f"{args.phone}: {len(orders)} orders")
        for o in orders:
            print(f"  {o['order_id']}  {o['status']:<9}  total={o['total_items']}")
    return 0


def cmd_resource_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[object] = []
    if args.kind:
        where.append("kind = ?")
        params.append(args.kind)
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    sql = "SELECT * FROM resources"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rowid"
    resources = []
    for r in conn.execute(sql, params).fetchall():
        d = _db.resource_dict(r)
        d["occupant"] = _resource_occupant(conn, r["resource_id"])
        resources.append(d)
    if args.json:
        _emit({"resources": resources})
    else:
        for d in resources:
            who = d["occupant"]["lot_id"] if d["occupant"] else "-"
            print(f"{d['resource_id']:<10}  {d['status']:<11}  {who}")
    return 0


def cmd_resource_set(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    r = _find_resource(conn, args.resource)
    if not r:
        _err(f"resource not found: {args.resource}")
        return 1
    conn.execute("UPDATE resources SET status = ? WHERE resource_id = ?",
                 (args.status, args.resource))
    conn.commit()
    if args.json:
        _emit({"resource": _db.resource_dict(_find_resource(conn, args.resource))})
    else:
        print(f"{args.resource} -> {args.status}")
    return 0


def cmd_data_export(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    table = _EXPORT_TABLES[args.table]
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    if args.format == "json":
        text = _json.dumps({args.table: rows}, ensure_ascii=False, indent=2)
    else:
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        text = buf.getvalue()
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print(f"Wrote {len(rows)} rows to {args.out}")
    else:
        print(text)
    return 0


def cmd_data_reset(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    conn.execute("DELETE FROM lot_events")
    conn.execute("DELETE FROM lots")
    conn.execute("DELETE FROM orders")
    conn.execute("DELETE FROM resources")
    _db.seed_resources(conn)
    conn.commit()
    if args.json:
        _emit({"ok": True})
    else:
        print("Data reset — resource pool re-seeded.")
    return 0


def cmd_resource_add(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if args.count < 1:
        _err("--count must be >= 1")
        return 1
    rows = conn.execute(
        "SELECT resource_id FROM resources WHERE kind = ?", (args.kind,)
    ).fetchall()
    max_idx = 0
    for r in rows:
        try:
            max_idx = max(max_idx, int(r["resource_id"].rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    added = []
    for i in range(max_idx + 1, max_idx + 1 + args.count):
        rid = f"{args.kind}-{i}"
        label = f"{_db.RESOURCE_KIND_LABELS[args.kind]} {i}"
        conn.execute(
            "INSERT INTO resources (resource_id, kind, label, status) VALUES (?, ?, ?, 'free')",
            (rid, args.kind, label),
        )
        added.append(rid)
    conn.commit()
    if args.json:
        _emit({"added": added})
    else:
        print(f"Added {len(added)}: {', '.join(added)}")
    return 0


def cmd_resource_retire(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    r = _find_resource(conn, args.resource)
    if not r:
        _err(f"resource not found: {args.resource}")
        return 1
    if _resource_occupant(conn, args.resource):
        _err(f"resource is occupied: {args.resource}")
        return 1
    conn.execute("DELETE FROM resources WHERE resource_id = ?", (args.resource,))
    conn.commit()
    if args.json:
        _emit({"retired": args.resource})
    else:
        print(f"Retired {args.resource}")
    return 0


def cmd_dashboard(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    resources = []
    for r in conn.execute("SELECT * FROM resources ORDER BY rowid").fetchall():
        d = _db.resource_dict(r)
        d["occupant"] = _resource_occupant(conn, r["resource_id"])
        resources.append(d)

    orders = []
    for r in conn.execute(
        "SELECT * FROM orders WHERE status = 'active' ORDER BY created_at DESC"
    ).fetchall():
        o = _db.order_dict(r)
        o["lots"] = _order_lots(conn, r["order_id"])
        orders.append(o)

    steps: dict[str, list[dict]] = {s: [] for s in _db.STEPS}
    for r in conn.execute("SELECT * FROM lots WHERE status = 'active'").fetchall():
        lot = _db.lot_dict(r)
        steps.setdefault(lot["step"], []).append(lot)

    _emit({"resources": resources, "orders": orders, "steps": steps})
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
    p.add_argument("--item", action="append", dest="items", default=None,
                   metavar="TYPE:QTY", help="declared item line, repeatable, e.g. --item khăn:100")
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

    p = order.add_parser("deliver", help="deliver a whole order (all parts must be counted)")
    p.add_argument("--order", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_deliver)

    p = order.add_parser("cancel", help="cancel an order and free its resources")
    p.add_argument("--order", required=True)
    p.add_argument("--reason", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_order_cancel)

    lot = sub.add_parser("lot", help="lot (part) operations").add_subparsers(
        dest="cmd", required=True)

    p = lot.add_parser("move", help="move a lot into a resource (step inferred)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--lot", help="lot id to move")
    src.add_argument("--from", dest="from_resource",
                     help="resolve the active lot currently in this resource, e.g. bin-1")
    p.add_argument("--to", required=True, help="target resource_id, e.g. washer-3 or bin-5")
    p.add_argument("--force", action="store_true", help="override a busy target")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_move)

    p = lot.add_parser("count", help="record counted item quantity for a lot")
    p.add_argument("--lot", required=True)
    p.add_argument("--items", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_count)

    p = lot.add_parser("redo", help="send a lot back to an earlier step (default giat)")
    p.add_argument("--lot", required=True)
    p.add_argument("--to", default=None, choices=_db.STEPS)
    p.add_argument("--notes", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_redo)

    p = lot.add_parser("deliver", help="mark a single lot delivered/done")
    p.add_argument("--lot", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_lot_deliver)

    customer = sub.add_parser("customer", help="customer lookups").add_subparsers(
        dest="cmd", required=True)
    p = customer.add_parser("history", help="all orders for a phone number")
    p.add_argument("--phone", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_customer_history)

    resource = sub.add_parser("resource", help="resource pool operations").add_subparsers(
        dest="cmd", required=True)
    p = resource.add_parser("list", help="list the resource pool")
    p.add_argument("--kind", choices=["bin", "washer", "dryer", "fold", "count"], default=None)
    p.add_argument("--status", choices=["free", "busy", "maintenance"], default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_list)
    p = resource.add_parser("set", help="manually set a resource status")
    p.add_argument("--resource", required=True)
    p.add_argument("--status", required=True, choices=["free", "busy", "maintenance"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_set)
    p = resource.add_parser("add", help="append N resources of a kind")
    p.add_argument("--kind", required=True, choices=["bin", "washer", "dryer", "fold", "count"])
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_add)
    p = resource.add_parser("retire", help="remove a (free) resource from the pool")
    p.add_argument("--resource", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_resource_retire)

    data = sub.add_parser("data", help="bulk data + lifecycle operations").add_subparsers(
        dest="cmd", required=True)
    p = data.add_parser("export", help="export a table to csv/json")
    p.add_argument("--table", choices=list(_EXPORT_TABLES), default="orders")
    p.add_argument("--format", choices=["csv", "json"], default="json")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_data_export)
    p = data.add_parser("reset", help="wipe all data and re-seed the resource pool")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_data_reset)

    p = sub.add_parser("dashboard", help="emit the full dashboard JSON payload")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_dashboard)

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
