#!/usr/bin/env python
"""Traffic / time-ban checker (cấm tải / cấm giờ) for the logistics module.

Given a destination zone, a delivery time, and a truck's registration capacity
(TTĐK), decides whether that truck is legally allowed into the zone at that time,
and if not, when the next legal window is. Rules live in ../data/traffic_bans.csv
as per-threshold rows (a zone can have several rows for different weight cutoffs).

IMPORTANT: ban evaluation keys off the truck's TTĐK (trọng tải đăng kiểm /
registration capacity), NOT the rated weight class. A truck rated 5T but
registered 4.9T is treated as 4.9T for bans.

Subcommand: check --zone <z> --time <HH:MM> --ttdk <t>
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "traffic_bans.csv"

DAY = 24 * 60


def _norm(text: str) -> str:
    """ASCII-fold Vietnamese: drop diacritics, đ->d, lowercase, collapse spaces."""
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.lower().split())


def _to_min(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def _fmt(minute: int) -> str:
    minute %= DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_windows(spec: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part:
            continue
        start, end = part.split("-")
        out.append((_to_min(start), _to_min(end)))
    return out


def _in_window(minute: int, win: tuple[int, int]) -> bool:
    start, end = win
    minute %= DAY
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end  # wraps past midnight


def _applies(row: dict, ttdk: float) -> bool:
    try:
        threshold = float(row["weight_threshold_t"])
    except (ValueError, KeyError):
        return False
    cmp = (row.get("comparator") or "gt").strip().lower()
    return {
        "gt": ttdk > threshold,
        "ge": ttdk >= threshold,
        "lt": ttdk < threshold,
        "le": ttdk <= threshold,
    }.get(cmp, False)


def _row_bans_at(minute: int, row: dict) -> bool:
    bans = _parse_windows(row.get("ban_windows", ""))
    allows = _parse_windows(row.get("allowed_windows", ""))
    if bans:
        if any(_in_window(minute, w) for w in bans):
            return True
    if allows:
        if not any(_in_window(minute, w) for w in allows):
            return True
    return False


def _is_allowed(minute: int, rows: list[dict]) -> bool:
    return not any(_row_bans_at(minute, r) for r in rows)


def _load_rows() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _match_zone(query: str, rows: list[dict]) -> tuple[list[dict], str | None]:
    nq = _norm(query)
    matched: list[dict] = []
    zone_label: str | None = None
    for r in rows:
        nz = _norm(r.get("zone", ""))
        if not nz:
            continue
        if nz in nq or nq in nz:
            matched.append(r)
            if zone_label is None:
                zone_label = r.get("zone")
    return matched, zone_label


def cmd_check(args: argparse.Namespace) -> int:
    all_rows = _load_rows()
    zone_rows_all, zone_label = _match_zone(args.zone, all_rows)
    t = _to_min(args.time)

    if not zone_rows_all:
        print(json.dumps({
            "zone": args.zone, "zone_matched": None, "ttdk": args.ttdk, "time": args.time,
            "allowed": True,
            "warning": "Không tìm thấy quy định cấm tải/cấm giờ cho khu vực này - cần kiểm tra thủ công trước khi nhận đơn.",
            "matched_rules": [], "next_allowed_window": None,
            "must_exit_before": None, "defer_to_next_day_suggested": False,
        }, ensure_ascii=False))
        return 0

    applicable = [r for r in zone_rows_all if _applies(r, args.ttdk)]
    allowed_now = _is_allowed(t, applicable)

    # Which applicable rows actually ban at the requested time (for the reason text).
    banning = [r for r in applicable if _row_bans_at(t, r)]

    next_window = None
    must_exit_before = None
    defer = False

    if not allowed_now:
        # Find the next minute (within 24h) the truck becomes allowed.
        start = None
        for d in range(1, DAY + 1):
            m = (t + d) % DAY
            if _is_allowed(m, applicable):
                start = m
                break
        if start is not None:
            end = start
            for d in range(1, DAY + 1):
                m = (start + d) % DAY
                if not _is_allowed(m, applicable):
                    break
                end = m
            next_window = f"{_fmt(start)}-{_fmt((end + 1) % DAY)}"
            # Heuristic: if the only legal window today is night (>=22:00 or <06:00),
            # flag that deferring to next day may be cleaner than a long wait.
            if start >= _to_min("22:00") or start < _to_min("06:00"):
                defer = True
    else:
        # Allowed now: when does it flip to banned? (the "must be out before" boundary)
        for d in range(1, DAY + 1):
            m = (t + d) % DAY
            if not _is_allowed(m, applicable):
                must_exit_before = _fmt(m)
                break

    reason_rules = banning if banning else applicable
    reason = "; ".join(r.get("notes", "").strip() for r in reason_rules if r.get("notes")) or None

    print(json.dumps({
        "zone": args.zone,
        "zone_matched": zone_label,
        "ttdk": args.ttdk,
        "time": args.time,
        "allowed": allowed_now,
        "reason": reason,
        "matched_rules": [{
            "comparator": r.get("comparator"),
            "weight_threshold_t": r.get("weight_threshold_t"),
            "ban_windows": r.get("ban_windows"),
            "allowed_windows": r.get("allowed_windows"),
            "bans_at_time": _row_bans_at(t, r),
            "notes": r.get("notes"),
        } for r in applicable],
        "next_allowed_window": next_window,
        "must_exit_before": must_exit_before,
        "defer_to_next_day_suggested": defer,
    }, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Traffic/time-ban checker (cấm tải/cấm giờ).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="check if a truck may enter a zone at a time")
    p.add_argument("--zone", required=True, help="destination zone (diacritic-insensitive)")
    p.add_argument("--time", required=True, help="delivery time HH:MM")
    p.add_argument("--ttdk", type=float, required=True, help="truck registration capacity (TTĐK) in tonnes")
    p.set_defaults(fn=cmd_check)

    args = parser.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
