#!/usr/bin/env python
"""Generic CSV explorer for a data module (auto-generated).

All subcommands print JSON to stdout:
  list                                          -> {"datasets":[{name,rows,columns,size}]}
  preview --file F [--limit N]                  -> {"file","columns","rows":[[...]]}
  query --file F [--filter S] [--column C] [--limit N]

CSV datasets live in ../data/ next to this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _csv_files():
    if not DATA_DIR.is_dir():
        return []
    return sorted(p for p in DATA_DIR.rglob("*.csv") if p.is_file())


def _rel(p: Path) -> str:
    return p.relative_to(DATA_DIR).as_posix()


def _resolve(file: str) -> Path:
    p = (DATA_DIR / file).resolve()
    try:
        p.relative_to(DATA_DIR.resolve())
    except ValueError:
        raise SystemExit(f"path outside data dir: {file}")
    if not p.is_file():
        raise SystemExit(f"file not found: {file}")
    return p


def _header_and_count(path: Path):
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        count = sum(1 for _ in reader)
    return header, count


def cmd_list() -> dict:
    out = []
    for p in _csv_files():
        try:
            header, count = _header_and_count(p)
            size = p.stat().st_size
        except OSError:
            continue
        out.append({"name": _rel(p), "rows": count, "columns": header, "size": size})
    return {"datasets": out}


def cmd_preview(file: str, limit: int) -> dict:
    p = _resolve(file)
    with p.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        rows = []
        for row in reader:
            if len(rows) >= limit:
                break
            rows.append(row)
    return {"file": file, "columns": header, "rows": rows}


def cmd_query(file: str, filter_s: str, column: str, limit: int) -> dict:
    p = _resolve(file)
    with p.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        col_idx = header.index(column) if column and column in header else None
        needle = (filter_s or "").lower()
        rows = []
        for row in reader:
            if needle:
                if col_idx is not None:
                    hay = row[col_idx] if col_idx < len(row) else ""
                else:
                    hay = " ".join(row)
                if needle not in hay.lower():
                    continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return {"file": file, "columns": header, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generic CSV explorer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_prev = sub.add_parser("preview")
    p_prev.add_argument("--file", required=True)
    p_prev.add_argument("--limit", type=int, default=100)
    p_q = sub.add_parser("query")
    p_q.add_argument("--file", required=True)
    p_q.add_argument("--filter", default="")
    p_q.add_argument("--column", default="")
    p_q.add_argument("--limit", type=int, default=100)
    # Tolerate a stray --json flag from dashboard callers.
    for sp in (sub.choices["list"], p_prev, p_q):
        sp.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.cmd == "list":
        result = cmd_list()
    elif args.cmd == "preview":
        result = cmd_preview(args.file, args.limit)
    else:
        result = cmd_query(args.file, args.filter, args.column, args.limit)
    json.dump(result, sys.stdout, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
