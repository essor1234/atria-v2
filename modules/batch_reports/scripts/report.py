#!/usr/bin/env python3
"""batch_reports — per-region sales reports that fan out, then merge.

Each ``gen --region <name>`` is a fully independent unit of work: it derives
deterministic synthetic metrics from the region name and writes one JSON report.
``merge`` aggregates every generated report into a ranked summary.

The design is deliberately "dispatch-shaped": a request spanning many regions
splits into one independent ``gen`` subtask per region plus a single ``merge``
that depends on all of them — exactly the kind of DAG the ``solve`` tool
(strategy=divide) fans out across background subagents.

Stdlib only. Output dir defaults to ``<module>/data`` and can be overridden with
``ATRIA_BATCH_REPORTS_DIR`` (used by tests).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parent.parent
_DATA = Path(os.environ.get("ATRIA_BATCH_REPORTS_DIR", str(_MODULE_ROOT / "data")))
_REPORTS = _DATA / "reports"


def _reports_dir() -> Path:
    _REPORTS.mkdir(parents=True, exist_ok=True)
    return _REPORTS


def _metrics(region: str) -> dict:
    """Deterministic synthetic metrics derived from the region name."""
    h = int(hashlib.sha256(region.strip().lower().encode()).hexdigest(), 16)
    units = 500 + h % 4500
    price = 5 + (h >> 16) % 20
    returns = round((h >> 32) % 8 / 100, 4)  # 0–7% return rate
    revenue = round(units * price * (1 - returns), 2)
    return {"units": units, "avg_price": price, "return_rate": returns, "revenue": revenue}


def _emit(obj: dict, as_json: bool, human: str) -> None:
    print(json.dumps(obj, ensure_ascii=False) if as_json else human)


def cmd_gen(args: argparse.Namespace) -> int:
    region = args.region.strip()
    if not region:
        _emit({"ok": False, "error": "region is required"}, args.json, "error: region is required")
        return 2
    # Simulate a non-trivial unit of work so parallel dispatch is visibly faster.
    if args.sleep > 0:
        time.sleep(args.sleep)
    metrics = _metrics(region)
    report = {"region": region, "generated_at": int(time.time()), **metrics}
    path = _reports_dir() / f"{region.lower().replace('/', '_')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    _emit(
        {"ok": True, "region": region, "path": str(path), **metrics},
        args.json,
        f"[gen] {region}: units={metrics['units']} revenue={metrics['revenue']} -> {path}",
    )
    return 0


def _load_reports() -> list[dict]:
    out = []
    for p in sorted(_reports_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:  # noqa: BLE001 — skip unreadable/partial files
            continue
    return out


def cmd_merge(args: argparse.Namespace) -> int:
    reports = _load_reports()
    if not reports:
        _emit({"ok": False, "error": "no reports to merge"}, args.json, "error: no reports yet")
        return 1
    ranked = sorted(reports, key=lambda r: r.get("revenue", 0), reverse=True)
    summary = {
        "regions": len(ranked),
        "total_units": sum(r.get("units", 0) for r in ranked),
        "total_revenue": round(sum(r.get("revenue", 0) for r in ranked), 2),
        "top_region": ranked[0]["region"],
        "ranking": [{"region": r["region"], "revenue": r.get("revenue", 0)} for r in ranked],
    }
    out = Path(args.out) if args.out else _DATA / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    _emit(
        {"ok": True, "path": str(out), **summary},
        args.json,
        f"[merge] {summary['regions']} regions, total_revenue={summary['total_revenue']}, "
        f"top={summary['top_region']} -> {out}",
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    reports = _load_reports()
    _emit(
        {"ok": True, "count": len(reports), "regions": [r["region"] for r in reports]},
        args.json,
        "\n".join(f"{r['region']}: revenue={r.get('revenue', 0)}" for r in reports)
        or "(no reports yet)",
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = _reports_dir() / f"{args.region.strip().lower().replace('/', '_')}.json"
    if not path.exists():
        _emit({"ok": False, "error": "not found"}, args.json, f"error: no report for {args.region}")
        return 1
    report = json.loads(path.read_text())
    _emit(report, args.json, json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Emit the full dashboard payload (regions ranked + summary if merged)."""
    reports = sorted(_load_reports(), key=lambda r: r.get("revenue", 0), reverse=True)
    summary = None
    sp = _DATA / "summary.json"
    if sp.exists():
        try:
            summary = json.loads(sp.read_text())
        except Exception:  # noqa: BLE001
            summary = None
    payload = {
        "ok": True,
        "count": len(reports),
        "regions": reports,
        "summary": summary,
        "total_units": sum(r.get("units", 0) for r in reports),
        "total_revenue": round(sum(r.get("revenue", 0) for r in reports), 2),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    n = 0
    if _REPORTS.exists():
        for p in _REPORTS.glob("*.json"):
            p.unlink()
            n += 1
    summary = _DATA / "summary.json"
    if summary.exists():
        summary.unlink()
    _emit({"ok": True, "removed": n}, args.json, f"[reset] removed {n} report(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --json on a shared parent so it works before OR after the subcommand
    # (e.g. both `report.py --json gen ...` and `report.py gen ... --json`).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")

    p = argparse.ArgumentParser(
        prog="report.py", description="Per-region batch reports.", parents=[common]
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "gen", parents=[common], help="generate the report for ONE region (independent unit)"
    )
    g.add_argument("--region", required=True)
    g.add_argument("--sleep", type=float, default=1.5, help="simulated work seconds (default 1.5)")
    g.set_defaults(func=cmd_gen)

    m = sub.add_parser(
        "merge", parents=[common], help="aggregate all region reports into a ranked summary"
    )
    m.add_argument("--out", default="", help="output path (default <module>/data/summary.json)")
    m.set_defaults(func=cmd_merge)

    sub.add_parser("list", parents=[common], help="list generated region reports").set_defaults(
        func=cmd_list
    )

    s = sub.add_parser("show", parents=[common], help="print one region's report")
    s.add_argument("--region", required=True)
    s.set_defaults(func=cmd_show)

    sub.add_parser(
        "dashboard", parents=[common], help="emit the dashboard JSON payload"
    ).set_defaults(func=cmd_dashboard)

    sub.add_parser(
        "reset", parents=[common], help="delete all generated reports + summary"
    ).set_defaults(func=cmd_reset)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
