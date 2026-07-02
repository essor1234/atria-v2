#!/usr/bin/env python
"""Truck recommender for the logistics module.

Ranks and SURFACES candidate trucks for a booking — it deliberately does NOT
hard-filter on capacity, so a near-boundary truck (e.g. a TTĐK 4.9T truck for a
5T order, used because Biên Hoà bans TTĐK >5T in the daytime) still reaches the
caller with a flag rather than being silently dropped. The LLM picks the final
truck and explains the capacity / ban / upsell tradeoff.

Deterministic here: CBM resolution by (weight_class, brand), capacity-vs-TTĐK
comparison, the numeric 8T->15T 80% upsell flags, and (if --zone/--time given)
per-truck ban status. Judgment (offer the upsell? wait vs defer?) is the LLM's.

Subcommand: match --weight <t> --cbm <m3> [--zone <z>] [--time HH:MM] [--new-customer]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FLEET_PATHS = {"dki": DATA_DIR / "dki.csv", "dki2": DATA_DIR / "dki2.csv"}
SPECS_PATH = DATA_DIR / "truck_specs.csv"

# Reuse the ban-evaluation helpers so ranking and the standalone checker agree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bans  # noqa: E402

NEAR_BOUNDARY_RATIO = 0.95   # TTĐK within 5% under the order -> surface as near_boundary
UPSELL_CLASS_RATIO = 1.4     # truck class this much bigger than the order -> upsell candidate


def _class_to_t(weight_class: str) -> float | None:
    s = (weight_class or "").strip().upper().rstrip("T").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _load_specs() -> dict[tuple[str, str], str]:
    specs: dict[tuple[str, str], str] = {}
    if not SPECS_PATH.exists():
        return specs
    with SPECS_PATH.open("r", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            specs[(r["weight_class"].strip(), r["brand"].strip())] = (r.get("cbm") or "").strip()
    return specs


def _cbm_for(specs: dict, weight_class: str, brand: str) -> float | None:
    raw = specs.get((weight_class.strip(), brand.strip()))
    if raw is None:
        raw = specs.get((weight_class.strip(), "*"))  # brand-agnostic fallback
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _load_fleet() -> list[dict]:
    rows: list[dict] = []
    for source, path in FLEET_PATHS.items():
        if not path.exists():
            continue
        with path.open("r", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                r["_source"] = source
                rows.append(r)
    return rows


def cmd_match(args: argparse.Namespace) -> int:
    specs = _load_specs()
    fleet = _load_fleet()
    weight = args.weight

    # Pre-load ban rules once if a zone is supplied.
    ban_rows = bans._load_rows() if args.zone else []
    zone_applicable = None
    if args.zone:
        zone_applicable, _ = bans._match_zone(args.zone, ban_rows)
    t_min = bans._to_min(args.time) if (args.zone and args.time) else None

    candidates = []
    for r in fleet:
        try:
            ttdk = float(r.get("ttdk_capacity") or 0)
        except ValueError:
            ttdk = 0.0
        class_t = _class_to_t(r.get("weight_class", ""))
        cbm = _cbm_for(specs, r.get("weight_class", ""), r.get("brand", ""))

        # Capacity fit keys off TTĐK (registration capacity), not the rated class.
        if ttdk >= weight:
            capacity_fit = "fits"
        elif ttdk >= weight * NEAR_BOUNDARY_RATIO:
            capacity_fit = "near_boundary"
        else:
            capacity_fit = "under"

        if cbm is None:
            cbm_fit = "unknown"
        elif args.cbm is None:
            cbm_fit = "unknown"
        elif args.cbm <= cbm:
            cbm_fit = "fits"
        else:
            cbm_fit = "insufficient"

        flags: list[str] = []
        upsell = None
        if capacity_fit == "near_boundary":
            flags.append("ban_tradeoff_candidate")
        if class_t is not None and weight > 0 and class_t >= weight * UPSELL_CLASS_RATIO:
            flags.append("upsell_bigger_truck")
            upsell = {
                "offer": True,
                "use_pct_limit": 80,
                "overflow_price_class": r.get("weight_class"),
                "new_customer_only": True,
                "note": "Cho khách dùng tối đa 80% tải; nếu dùng 100% tính giá theo "
                        f"{r.get('weight_class')} (chỉ áp dụng khách mới).",
            }
        if r.get("status", "").lower() == "busy":
            flags.append("busy")

        ban_status = None
        if zone_applicable is not None:
            appl = [row for row in zone_applicable if bans._applies(row, ttdk)]
            if t_min is not None:
                allowed = bans._is_allowed(t_min, appl)
                ban_status = {"zone": args.zone, "time": args.time, "allowed": allowed}
                if not allowed:
                    flags.append("banned_at_time")
            else:
                ban_status = {"zone": args.zone, "rules_apply": len(appl)}

        # Ranking score: prefer allowed, free, capacity fit, cbm fit, least excess.
        excess = (ttdk - weight) if ttdk >= weight else 999  # under-capacity sinks
        score = (
            0 if (ban_status and ban_status.get("allowed") is False) else 1,
            1 if r.get("status", "").lower() == "free" else 0,
            {"fits": 2, "near_boundary": 1, "under": 0}[capacity_fit],
            0 if cbm_fit == "insufficient" else 1,
            -excess,
        )

        candidates.append((score, {
            "vehicle_number": r.get("vehicle_number"),
            "driver_name": r.get("driver_name"),
            "source": r.get("_source"),
            "weight_class": r.get("weight_class"),
            "brand": r.get("brand"),
            "ttdk_capacity": ttdk,
            "status": r.get("status"),
            "cbm": cbm,
            "capacity_fit": capacity_fit,
            "cbm_fit": cbm_fit,
            "flags": flags,
            "upsell": upsell,
            "ban_status": ban_status,
        }))

    candidates.sort(key=lambda c: c[0], reverse=True)
    ranked = [c[1] for c in candidates]
    recommended = [c["vehicle_number"] for c in ranked
                   if c["capacity_fit"] in ("fits", "near_boundary")
                   and c["cbm_fit"] != "insufficient"
                   and "busy" not in c["flags"]
                   and "banned_at_time" not in c["flags"]]

    print(json.dumps({
        "request": {"weight_t": weight, "cbm": args.cbm, "zone": args.zone,
                    "time": args.time, "new_customer": args.new_customer},
        "recommended": recommended,
        "candidates": ranked,
    }, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Logistics truck recommender.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("match", help="rank candidate trucks for a booking")
    p.add_argument("--weight", type=float, required=True, help="requested load in tonnes")
    p.add_argument("--cbm", type=float, help="requested volume in CBM (optional)")
    p.add_argument("--zone", help="destination zone (enables ban check)")
    p.add_argument("--time", help="delivery time HH:MM (with --zone, checks ban at time)")
    p.add_argument("--new-customer", dest="new_customer", action="store_true")
    p.set_defaults(fn=cmd_match)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
