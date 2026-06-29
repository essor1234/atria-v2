#!/usr/bin/env python
"""Push the warehouse item-form block into the active chat session.

Optionally pre-fills the form by reading the current row from the CSV.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import _db


def _load_all() -> list[dict]:
    conn = _db.connect()
    try:
        return [_db.item_dict(r) for r in conn.execute("SELECT * FROM items").fetchall()]
    finally:
        conn.close()


def _load_row(rows: list[dict], sku: str) -> dict | None:
    for row in rows:
        if row["sku"] == sku:
            return row
    return None


def _distinct(rows: list[dict], field: str) -> list[str]:
    seen: dict[str, None] = {}
    for r in rows:
        v = str(r.get(field) or "").strip()
        if v and v not in seen:
            seen[v] = None
    return sorted(seen.keys())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Push warehouse item form to chat UI.")
    parser.add_argument("--sku", help="pre-fill the form from this SKU; omit to create a new item")
    parser.add_argument("--title", default=None, help="override the block title")
    args = parser.parse_args(argv[1:])

    session_id = os.environ.get("ATRIA_SESSION_ID")
    api_base = os.environ.get("ATRIA_API_BASE")
    if not session_id:
        print("ERROR: ATRIA_SESSION_ID is not set (no active chat session).", file=sys.stderr)
        return 2
    if not api_base:
        print("ERROR: ATRIA_API_BASE is not set (server URL unknown).", file=sys.stderr)
        return 2

    rows = _load_all()
    suggestions = {
        "sku": _distinct(rows, "sku"),
        "name": _distinct(rows, "name"),
        "location": _distinct(rows, "location"),
    }

    if args.sku:
        row = _load_row(rows, args.sku)
        if row is None:
            print(f"ERROR: SKU not found: {args.sku}", file=sys.stderr)
            return 1
        props = {"mode": "edit", "item": row, "suggestions": suggestions}
        title = args.title or f"Edit {args.sku}"
    else:
        props = {"mode": "create", "item": {}, "suggestions": suggestions}
        title = args.title or "New inventory item"

    body = json.dumps({
        "session_id": session_id,
        "module": "warehouse",
        "block": "item_form",
        "props": props,
        "title": title,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/blocks/push",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: push failed ({exc.code}): {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: cannot reach {api_base}: {exc.reason}", file=sys.stderr)
        return 1

    print(f"pushed item_form block: id={payload.get('block_id')} mode={props['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
