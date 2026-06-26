from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "modules" / "item_flow_tracking" / "scripts" / "flow.py"


@pytest.fixture()
def env(tmp_path):
    """Point the flow CLI at an isolated, freshly-seeded temp DB."""
    e = os.environ.copy()
    e["ATRIA_FLOW_DB"] = str(tmp_path / "flow.db")
    return e


def run(env, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False, env=env,
    )


def run_json(env, *args: str) -> dict:
    r = run(env, *args, "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── schema + seeded resource pool ────────────────────────────────────────────


def test_fresh_db_seeds_resource_pool(env):
    payload = run_json(env, "resource", "list")
    kinds = {}
    for r in payload["resources"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    assert kinds == {"bin": 15, "washer": 10, "dryer": 10, "fold": 1, "count": 1}
    assert all(r["status"] == "free" for r in payload["resources"])


# ── orders + lots at intake ──────────────────────────────────────────────────


def test_order_new_creates_lots_and_assigns_bins(env):
    payload = run_json(env, "order", "new", "--phone", "0901234567",
                       "--name", "Khach A", "--bins", "3")
    order = payload["order"]
    lots = payload["lots"]
    assert order["order_id"].startswith("DH-")
    assert order["customer_phone"] == "0901234567"
    assert order["status"] == "active"
    assert len(lots) == 3
    assert {lot["label"] for lot in lots} == {"P1", "P2", "P3"}
    assert all(lot["step"] == "nhan_hang" for lot in lots)
    bins = [lot["current_resource"] for lot in lots]
    assert all(b.startswith("bin-") for b in bins)
    assert len(set(bins)) == 3  # distinct bins

    res = run_json(env, "resource", "list", "--status", "busy")
    busy = {r["resource_id"] for r in res["resources"]}
    assert set(bins) <= busy


def test_order_new_rejects_when_not_enough_bins(env):
    r = run(env, "order", "new", "--phone", "0900000000", "--bins", "16", "--json")
    assert r.returncode != 0
    assert "free bins" in r.stderr


def test_order_ids_increment_per_day(env):
    a = run_json(env, "order", "new", "--phone", "0900000001", "--bins", "1")["order"]["order_id"]
    b = run_json(env, "order", "new", "--phone", "0900000002", "--bins", "1")["order"]["order_id"]
    assert a != b
    assert a.endswith("-001") and b.endswith("-002")


def test_order_show_lists_parts(env):
    new = run_json(env, "order", "new", "--phone", "0901112223", "--bins", "2")
    oid = new["order"]["order_id"]
    shown = run_json(env, "order", "show", "--order", oid)
    assert shown["order"]["order_id"] == oid
    assert len(shown["order"]["lots"]) == 2
