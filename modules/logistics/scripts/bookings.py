#!/usr/bin/env python
"""Booking CRUD for the logistics module.

A booking is one or more line-item rows sharing a booking_id (one row per
assigned truck), so a single booking can span multiple trucks. On create the
booking gets a placeholder row with no vehicle; add-truck fills it (and appends
rows for further trucks), resolving the driver from the DKI / DKI 2 fleet.

Subcommands: create, add-truck, list, update, set-status, remove, reset.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CSV_PATH = DATA_DIR / "bookings.csv"
TEMPLATE_PATH = DATA_DIR / "bookings.template.csv"
FLEET_PATHS = [DATA_DIR / "dki.csv", DATA_DIR / "dki2.csv"]

FIELDS = [
    "booking_id",
    "customer",
    "created_at",
    "status",
    "destination_zone",
    "requested_weight_t",
    "vehicle_number",
    "driver_name",
    "delivery_time",
    "notes",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _norm_plate(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _ensure_csv() -> None:
    if not CSV_PATH.exists():
        if TEMPLATE_PATH.exists():
            shutil.copy(TEMPLATE_PATH, CSV_PATH)
        else:
            with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=FIELDS).writeheader()


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


def _fleet_lookup(vehicle: str) -> dict | None:
    target = _norm_plate(vehicle)
    for path in FLEET_PATHS:
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if _norm_plate(r.get("vehicle_number", "")) == target:
                    return r
    return None


def _next_id(rows: list[dict]) -> str:
    nums = []
    for r in rows:
        bid = r.get("booking_id", "")
        if bid.startswith("BK-"):
            try:
                nums.append(int(bid[3:]))
            except ValueError:
                pass
    return f"BK-{(max(nums) + 1 if nums else 1):04d}"


def cmd_create(args: argparse.Namespace) -> int:
    rows = _load()
    booking_id = _next_id(rows)
    rows.append({
        "booking_id": booking_id,
        "customer": args.customer,
        "created_at": _now(),
        "status": "open",
        "destination_zone": args.destination,
        "requested_weight_t": str(args.weight),
        "vehicle_number": "",
        "driver_name": "",
        "delivery_time": "",
        "notes": args.notes or "",
    })
    _save(rows)
    print(json.dumps({"created": booking_id, "customer": args.customer,
                      "destination_zone": args.destination,
                      "requested_weight_t": args.weight}, ensure_ascii=False))
    return 0


def cmd_add_truck(args: argparse.Namespace) -> int:
    rows = _load()
    booking_rows = [r for r in rows if r["booking_id"] == args.booking]
    if not booking_rows:
        print(f"ERROR: booking not found: {args.booking}", file=sys.stderr)
        return 1

    veh = _fleet_lookup(args.vehicle)
    if veh is None:
        print(f"ERROR: vehicle not in DKI/DKI2 fleet: {args.vehicle}", file=sys.stderr)
        return 1
    driver = veh.get("driver_name", "")

    # Fill an empty placeholder row if one exists; otherwise append a new line item.
    placeholder = next((r for r in booking_rows if not r.get("vehicle_number")), None)
    if placeholder is not None:
        placeholder["vehicle_number"] = veh["vehicle_number"]
        placeholder["driver_name"] = driver
        placeholder["delivery_time"] = args.delivery_time or ""
    else:
        ref = booking_rows[0]
        rows.append({
            "booking_id": args.booking,
            "customer": ref["customer"],
            "created_at": _now(),
            "status": ref["status"],
            "destination_zone": ref["destination_zone"],
            "requested_weight_t": ref["requested_weight_t"],
            "vehicle_number": veh["vehicle_number"],
            "driver_name": driver,
            "delivery_time": args.delivery_time or "",
            "notes": "",
        })
    _save(rows)
    print(json.dumps({"booking_id": args.booking, "added_vehicle": veh["vehicle_number"],
                      "driver_name": driver, "delivery_time": args.delivery_time},
                     ensure_ascii=False))
    return 0


def _group(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        bid = r["booking_id"]
        g = groups.setdefault(bid, {
            "booking_id": bid,
            "customer": r["customer"],
            "created_at": r["created_at"],
            "status": r["status"],
            "destination_zone": r["destination_zone"],
            "requested_weight_t": r["requested_weight_t"],
            "notes": r["notes"],
            "trucks": [],
        })
        if r.get("vehicle_number"):
            g["trucks"].append({
                "vehicle_number": r["vehicle_number"],
                "driver_name": r["driver_name"],
                "delivery_time": r["delivery_time"],
            })
    return list(groups.values())


def cmd_list(args: argparse.Namespace) -> int:
    rows = _load()
    if args.status:
        rows = [r for r in rows if r.get("status", "").lower() == args.status.lower()]
    grouped = _group(rows)
    if args.json:
        print(json.dumps({"bookings": grouped}, ensure_ascii=False))
        return 0
    if not grouped:
        print("(no bookings)")
        return 0
    for g in grouped:
        trucks = ", ".join(f"{t['vehicle_number']}/{t['driver_name']}@{t['delivery_time']}"
                           for t in g["trucks"]) or "(no trucks yet)"
        print(f"{g['booking_id']}  {g['customer']:<18} -> {g['destination_zone']:<18} "
              f"{g['requested_weight_t']}T  [{g['status']}]  {trucks}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    rows = _load()
    hit = [r for r in rows if r["booking_id"] == args.booking]
    if not hit:
        print(f"ERROR: booking not found: {args.booking}", file=sys.stderr)
        return 1
    for r in hit:
        if args.destination is not None:
            r["destination_zone"] = args.destination
        if args.weight is not None:
            r["requested_weight_t"] = str(args.weight)
        if args.notes is not None:
            r["notes"] = args.notes
        if args.status is not None:
            r["status"] = args.status
    _save(rows)
    print(json.dumps({"updated": args.booking, "rows": len(hit)}, ensure_ascii=False))
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    rows = _load()
    hit = [r for r in rows if r["booking_id"] == args.booking]
    if not hit:
        print(f"ERROR: booking not found: {args.booking}", file=sys.stderr)
        return 1
    for r in hit:
        r["status"] = args.status
    _save(rows)
    print(json.dumps({"booking_id": args.booking, "status": args.status}, ensure_ascii=False))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    rows = _load()
    kept = [r for r in rows if r["booking_id"] != args.booking]
    if len(kept) == len(rows):
        print(f"ERROR: booking not found: {args.booking}", file=sys.stderr)
        return 1
    _save(kept)
    print(json.dumps({"removed": args.booking}, ensure_ascii=False))
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    if TEMPLATE_PATH.exists():
        shutil.copy(TEMPLATE_PATH, CSV_PATH)
    else:
        _save([])
    print(json.dumps({"reset": str(CSV_PATH.name)}, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Logistics booking CRUD (multi-truck).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("create", help="create a booking (placeholder, no truck yet)")
    p_c.add_argument("--customer", required=True)
    p_c.add_argument("--destination", required=True, help="destination zone")
    p_c.add_argument("--weight", type=float, required=True, help="requested weight in tonnes")
    p_c.add_argument("--notes")
    p_c.set_defaults(fn=cmd_create)

    p_a = sub.add_parser("add-truck", help="assign a truck/driver to a booking")
    p_a.add_argument("--booking", required=True)
    p_a.add_argument("--vehicle", required=True)
    p_a.add_argument("--delivery-time", dest="delivery_time", help="HH:MM")
    p_a.set_defaults(fn=cmd_add_truck)

    p_l = sub.add_parser("list", help="list bookings (grouped by booking_id)")
    p_l.add_argument("--status")
    p_l.add_argument("--json", action="store_true")
    p_l.set_defaults(fn=cmd_list)

    p_u = sub.add_parser("update", help="patch fields on a booking")
    p_u.add_argument("--booking", required=True)
    p_u.add_argument("--destination")
    p_u.add_argument("--weight", type=float)
    p_u.add_argument("--notes")
    p_u.add_argument("--status")
    p_u.set_defaults(fn=cmd_update)

    p_s = sub.add_parser("set-status", help="set a booking's status")
    p_s.add_argument("--booking", required=True)
    p_s.add_argument("--status", required=True)
    p_s.set_defaults(fn=cmd_set_status)

    p_r = sub.add_parser("remove", help="delete a booking and all its trucks")
    p_r.add_argument("--booking", required=True)
    p_r.set_defaults(fn=cmd_remove)

    p_reset = sub.add_parser("reset", help="reset bookings to the empty template")
    p_reset.set_defaults(fn=cmd_reset)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
