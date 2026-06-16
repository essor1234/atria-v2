from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "modules" / "warehouse" / "scripts" / "inventory.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def test_list_json_returns_items_and_low_stock():
    r = _run("list", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert isinstance(payload["items"], list)
    assert all({"sku","name","location","quantity","unit_price","reorder_level"}
               .issubset(item.keys()) for item in payload["items"])
    assert isinstance(payload["low_stock"], list)
    by_sku = {it["sku"]: it for it in payload["items"]}
    for sku in payload["low_stock"]:
        it = by_sku[sku]
        assert int(it["quantity"]) <= int(it["reorder_level"])


def test_list_json_query_filter():
    r = _run("list", "--json", "--query", "widget")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert all("widget" in it["name"].lower() or "widget" in it["sku"].lower()
               for it in payload["items"])
