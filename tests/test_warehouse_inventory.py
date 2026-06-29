from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "modules" / "warehouse" / "scripts" / "inventory.py"


@pytest.fixture()
def env(tmp_path):
    """Point the warehouse CLI at an isolated, freshly-seeded temp DB."""
    e = os.environ.copy()
    e["ATRIA_WAREHOUSE_DB"] = str(tmp_path / "warehouse.db")
    return e


def run(env, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def list_json(env, *args: str) -> dict:
    r = run(env, "list", "--json", *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── seeding & listing ────────────────────────────────────────────────────────


def test_fresh_db_is_seeded(env):
    payload = list_json(env)
    skus = {it["sku"] for it in payload["items"]}
    assert {"SKU-001", "SKU-002", "SKU-003"} <= skus


def test_list_json_returns_items_and_low_stock(env):
    payload = list_json(env)
    assert isinstance(payload["items"], list)
    assert all(
        {"sku", "name", "location", "quantity", "unit_price", "reorder_level"}.issubset(item.keys())
        for item in payload["items"]
    )
    by_sku = {it["sku"]: it for it in payload["items"]}
    for sku in payload["low_stock"]:
        assert by_sku[sku]["quantity"] <= by_sku[sku]["reorder_level"]


def test_list_json_query_filter(env):
    payload = list_json(env, "--query", "widget")
    assert payload["items"]
    assert all(
        "widget" in it["name"].lower() or "widget" in it["sku"].lower() for it in payload["items"]
    )


def test_list_low_only(env):
    payload = list_json(env, "--low-only")
    assert all(it["quantity"] <= it["reorder_level"] for it in payload["items"])


# ── CRUD + audit ledger ───────────────────────────────────────────────────────


def test_add_logs_movement(env):
    r = run(
        env,
        "add",
        "--sku",
        "SKU-900",
        "--name",
        "Bolt",
        "--location",
        "Z1",
        "--quantity",
        "30",
        "--unit-price",
        "1.50",
        "--reorder-level",
        "5",
    )
    assert r.returncode == 0, r.stderr
    hist = json.loads(run(env, "history", "--sku", "SKU-900", "--json").stdout)["movements"]
    assert any(m["kind"] == "add" and m["delta"] == 30 for m in hist)


def test_add_duplicate_fails(env):
    r = run(
        env,
        "add",
        "--sku",
        "SKU-001",
        "--name",
        "Dup",
        "--location",
        "X",
        "--quantity",
        "1",
        "--unit-price",
        "1",
        "--reorder-level",
        "1",
    )
    assert r.returncode == 1
    assert "already exists" in r.stderr


def test_receive_and_ship_update_quantity(env):
    run(env, "receive", "--sku", "SKU-001", "--qty", "10", "--reference", "PO-1")
    run(env, "ship", "--sku", "SKU-001", "--qty", "4", "--reference", "ORD-1")
    by_sku = {it["sku"]: it for it in list_json(env)["items"]}
    assert by_sku["SKU-001"]["quantity"] == 56  # 50 + 10 - 4
    kinds = {
        m["kind"]
        for m in json.loads(run(env, "history", "--sku", "SKU-001", "--json").stdout)["movements"]
    }
    assert {"receive", "ship"} <= kinds


def test_ship_cannot_go_negative(env):
    r = run(env, "ship", "--sku", "SKU-003", "--qty", "999")
    assert r.returncode == 1
    assert "negative" in r.stderr


def test_adjust_negative_guard(env):
    r = run(env, "adjust", "--sku", "SKU-003", "--delta", "-999")
    assert r.returncode == 1


def test_move_changes_location(env):
    assert run(env, "move", "--sku", "SKU-001", "--location", "B9-99").returncode == 0
    by_sku = {it["sku"]: it for it in list_json(env)["items"]}
    assert by_sku["SKU-001"]["location"] == "B9-99"


def test_set_reorder(env):
    assert run(env, "set-reorder", "--sku", "SKU-001", "--level", "99").returncode == 0
    by_sku = {it["sku"]: it for it in list_json(env)["items"]}
    assert by_sku["SKU-001"]["reorder_level"] == 99
    assert "SKU-001" in list_json(env)["low_stock"]  # 50 <= 99


def test_remove(env):
    assert run(env, "remove", "--sku", "SKU-002").returncode == 0
    assert "SKU-002" not in {it["sku"] for it in list_json(env)["items"]}


# ── reporting ─────────────────────────────────────────────────────────────────


def test_summary_json(env):
    s = json.loads(run(env, "summary", "--json").stdout)
    assert s["skus"] == 3
    assert s["units"] == 65  # 50 + 12 + 3
    assert s["value"] == pytest.approx(50 * 9.99 + 12 * 24.50 + 3 * 4.25, rel=1e-6)
    assert s["low_stock_count"] == len(s["low_stock"])


def test_valuation_json(env):
    v = json.loads(run(env, "valuation", "--by", "location", "--json").stdout)
    assert v["by"] == "location"
    assert sum(g["units"] for g in v["groups"]) == 65


def test_low_stock_json(env):
    low = json.loads(run(env, "low-stock", "--json").stdout)
    assert all(it["quantity"] <= it["reorder_level"] for it in low["items"])


# ── read-only query guard ─────────────────────────────────────────────────────


def test_query_select_ok(env):
    r = run(env, "query", "--json", "--sql", "SELECT COUNT(*) AS n FROM items")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["rows"][0]["n"] == 3


def test_query_rejects_write(env):
    for sql in ("DELETE FROM items", "UPDATE items SET quantity=0", "SELECT 1; DROP TABLE items"):
        r = run(env, "query", "--sql", sql)
        assert r.returncode == 1, f"should reject: {sql}"


# ── import / export / reset ────────────────────────────────────────────────────


def test_export_import_roundtrip(env, tmp_path):
    out = tmp_path / "dump.json"
    assert run(env, "export", "--format", "json", "--out", str(out)).returncode == 0
    assert run(env, "reset").returncode == 0
    assert list_json(env)["items"] == []
    assert run(env, "import", "--file", str(out), "--format", "json").returncode == 0
    assert len(list_json(env)["items"]) == 3


def test_reset_empties_everything(env):
    assert run(env, "reset").returncode == 0
    assert list_json(env)["items"] == []
    assert json.loads(run(env, "history", "--json").stdout)["movements"] == []
