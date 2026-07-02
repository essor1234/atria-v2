#!/usr/bin/env python
"""Fleet/driver lookup for the logistics module.

Reads the DKI / DKI 2 fleet sheets (vehicle number -> driver name, phone, IDs,
weight class, brand, registration capacity / TTĐK, status). "DKI" is the
email-booking fleet, "DKI 2" the message-booking fleet.

Subcommands: lookup, list, set-status. All emit JSON to stdout with --json
(lookup always JSON). Source files live at ../data/dki.csv and ../data/dki2.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SOURCES = {"dki": DATA_DIR / "dki.csv", "dki2": DATA_DIR / "dki2.csv"}

FIELDS = [
    "vehicle_number",
    "driver_name",
    "phone",
    "national_id",
    "license_id",
    "weight_class",
    "brand",
    "ttdk_capacity",
    "status",
]


def _norm_plate(value: str) -> str:
    """Loose vehicle-number match: drop spaces/dots/dashes, uppercase."""
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _load(source: str) -> list[dict]:
    path = SOURCES[source]
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["_source"] = source
    return rows


def _all_rows(source: str | None) -> list[dict]:
    sources = [source] if source else list(SOURCES)
    rows: list[dict] = []
    for s in sources:
        rows.extend(_load(s))
    return rows


def _save(source: str, rows: list[dict]) -> None:
    path = SOURCES[source]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def cmd_lookup(args: argparse.Namespace) -> int:
    target = _norm_plate(args.vehicle)
    matches = [r for r in _all_rows(args.source) if _norm_plate(r["vehicle_number"]) == target]
    if not matches:
        print(json.dumps({"found": False, "vehicle_number": args.vehicle, "matches": []},
                         ensure_ascii=False))
        return 1
    clean = [{k: r.get(k, "") for k in FIELDS} | {"source": r["_source"]} for r in matches]
    print(json.dumps({"found": True, "vehicle_number": args.vehicle, "matches": clean},
                     ensure_ascii=False))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    rows = _all_rows(args.source)
    if args.status:
        rows = [r for r in rows if r.get("status", "").lower() == args.status.lower()]
    out = [{k: r.get(k, "") for k in FIELDS} | {"source": r["_source"]} for r in rows]
    if args.json:
        print(json.dumps({"vehicles": out}, ensure_ascii=False))
        return 0
    if not out:
        print("(no vehicles)")
        return 0
    for r in out:
        print(f"{r['vehicle_number']:<12} {r['weight_class']:<6} {r['brand']:<10} "
              f"TTĐK={r['ttdk_capacity']:<5} {r['status']:<10} {r['driver_name']} ({r['source']})")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    target = _norm_plate(args.vehicle)
    updated = 0
    for source in ([args.source] if args.source else list(SOURCES)):
        rows = _load(source)
        changed = False
        for r in rows:
            if _norm_plate(r["vehicle_number"]) == target:
                r["status"] = args.status
                changed = True
                updated += 1
        if changed:
            _save(source, rows)
    if not updated:
        print(f"ERROR: vehicle not found: {args.vehicle}", file=sys.stderr)
        return 1
    print(json.dumps({"updated": updated, "vehicle_number": args.vehicle, "status": args.status},
                     ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Logistics fleet/driver lookup (DKI / DKI 2).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_look = sub.add_parser("lookup", help="look up a vehicle number -> driver info")
    p_look.add_argument("--vehicle", required=True, help="vehicle/plate number (loose match)")
    p_look.add_argument("--source", choices=list(SOURCES), help="restrict to dki or dki2")
    p_look.set_defaults(fn=cmd_lookup)

    p_list = sub.add_parser("list", help="list vehicles")
    p_list.add_argument("--source", choices=list(SOURCES))
    p_list.add_argument("--status", help="filter by status (free/returning/busy)")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(fn=cmd_list)

    p_set = sub.add_parser("set-status", help="update a vehicle's status (manual GPS proxy)")
    p_set.add_argument("--vehicle", required=True)
    p_set.add_argument("--status", required=True, help="free / returning / busy")
    p_set.add_argument("--source", choices=list(SOURCES))
    p_set.set_defaults(fn=cmd_set_status)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
