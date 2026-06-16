#!/usr/bin/env python
"""CSV-backed inventory CRUD for the warehouse module.

Subcommands: list, add, update, adjust, remove, reset.
The CSV lives next to this script at ../data/inventory.csv.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "inventory.csv"
TEMPLATE_PATH = DATA_DIR / "inventory.template.csv"

FIELDS = ["sku", "name", "location", "quantity", "unit_price", "reorder_level", "updated_at"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_csv() -> None:
    if not CSV_PATH.exists():
        if not TEMPLATE_PATH.exists():
            raise SystemExit(f"template missing: {TEMPLATE_PATH}")
        shutil.copy(TEMPLATE_PATH, CSV_PATH)


def _load() -> list[dict]:
    _ensure_csv()
    with CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _save(rows: list[dict]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def _find(rows: list[dict], sku: str) -> int:
    for i, row in enumerate(rows):
        if row["sku"] == sku:
            return i
    return -1


def cmd_list(args: argparse.Namespace) -> int:
    rows = _load()
    if args.query:
        q = args.query.lower()
        rows = [r for r in rows if q in r["sku"].lower() or q in r["name"].lower()]

    low: list[str] = []
    for r in rows:
        try:
            if int(r["quantity"]) <= int(r["reorder_level"]):
                low.append(r["sku"])
        except ValueError:
            pass

    if args.json:
        import json as _json
        print(_json.dumps({"items": rows, "low_stock": low}))
        return 0

    if not rows:
        print("(no items)")
        return 0
    widths = {f: max(len(f), max((len(r.get(f, "")) for r in rows), default=0)) for f in FIELDS}
    line = "  ".join(f.ljust(widths[f]) for f in FIELDS)
    print(line)
    print("  ".join("-" * widths[f] for f in FIELDS))
    for r in rows:
        print("  ".join(r.get(f, "").ljust(widths[f]) for f in FIELDS))
    if low:
        print(f"\nlow stock (<= reorder_level): {', '.join(low)}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    rows = _load()
    if _find(rows, args.sku) >= 0:
        print(f"ERROR: SKU already exists: {args.sku}", file=sys.stderr)
        return 1
    rows.append({
        "sku": args.sku,
        "name": args.name,
        "location": args.location,
        "quantity": str(args.quantity),
        "unit_price": f"{args.unit_price:.2f}",
        "reorder_level": str(args.reorder_level),
        "updated_at": _now(),
    })
    _save(rows)
    print(f"added: {args.sku}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    rows = _load()
    idx = _find(rows, args.sku)
    if idx < 0:
        print(f"ERROR: SKU not found: {args.sku}", file=sys.stderr)
        return 1
    row = rows[idx]
    if args.name is not None:
        row["name"] = args.name
    if args.location is not None:
        row["location"] = args.location
    if args.quantity is not None:
        row["quantity"] = str(args.quantity)
    if args.unit_price is not None:
        row["unit_price"] = f"{args.unit_price:.2f}"
    if args.reorder_level is not None:
        row["reorder_level"] = str(args.reorder_level)
    row["updated_at"] = _now()
    _save(rows)
    print(f"updated: {args.sku}")
    return 0


def cmd_adjust(args: argparse.Namespace) -> int:
    rows = _load()
    idx = _find(rows, args.sku)
    if idx < 0:
        print(f"ERROR: SKU not found: {args.sku}", file=sys.stderr)
        return 1
    row = rows[idx]
    new_qty = int(row["quantity"]) + args.delta
    if new_qty < 0:
        print(f"ERROR: would go negative ({new_qty}) for {args.sku}", file=sys.stderr)
        return 1
    row["quantity"] = str(new_qty)
    row["updated_at"] = _now()
    _save(rows)
    print(f"adjusted: {args.sku} -> quantity={new_qty}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    rows = _load()
    idx = _find(rows, args.sku)
    if idx < 0:
        print(f"ERROR: SKU not found: {args.sku}", file=sys.stderr)
        return 1
    rows.pop(idx)
    _save(rows)
    print(f"removed: {args.sku}")
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template missing: {TEMPLATE_PATH}", file=sys.stderr)
        return 1
    shutil.copy(TEMPLATE_PATH, CSV_PATH)
    print(f"reset: {CSV_PATH}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Warehouse inventory CRUD.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list items")
    p_list.add_argument("--query", help="substring filter on sku/name")
    p_list.add_argument("--json", action="store_true", help="emit JSON for programmatic consumers")
    p_list.set_defaults(fn=cmd_list)

    p_add = sub.add_parser("add", help="add a new item")
    p_add.add_argument("--sku", required=True)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--location", required=True)
    p_add.add_argument("--quantity", type=int, required=True)
    p_add.add_argument("--unit-price", type=float, required=True)
    p_add.add_argument("--reorder-level", type=int, required=True)
    p_add.set_defaults(fn=cmd_add)

    p_upd = sub.add_parser("update", help="patch fields on an existing item")
    p_upd.add_argument("--sku", required=True)
    p_upd.add_argument("--name")
    p_upd.add_argument("--location")
    p_upd.add_argument("--quantity", type=int)
    p_upd.add_argument("--unit-price", type=float)
    p_upd.add_argument("--reorder-level", type=int)
    p_upd.set_defaults(fn=cmd_update)

    p_adj = sub.add_parser("adjust", help="add delta to quantity")
    p_adj.add_argument("--sku", required=True)
    p_adj.add_argument("--delta", type=int, required=True)
    p_adj.set_defaults(fn=cmd_adjust)

    p_rm = sub.add_parser("remove", help="delete an item")
    p_rm.add_argument("--sku", required=True)
    p_rm.set_defaults(fn=cmd_remove)

    p_reset = sub.add_parser("reset", help="reset CSV to the empty template")
    p_reset.set_defaults(fn=cmd_reset)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
