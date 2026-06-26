from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "modules" / "item_flow_tracking" / "scripts" / "flow.py"
)


@pytest.fixture()
def env(tmp_path):
    """Point the flow CLI at an isolated, freshly-seeded temp DB."""
    e = os.environ.copy()
    e["ATRIA_FLOW_DB"] = str(tmp_path / "flow.db")
    return e


def run(env, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
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
    payload = run_json(
        env, "order", "new", "--phone", "0901234567", "--name", "Khach A", "--bins", "3"
    )
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


# ── moving lots between resources ────────────────────────────────────────────


def _first_lot(env, phone="0905550000", bins=1):
    payload = run_json(env, "order", "new", "--phone", phone, "--bins", str(bins))
    return payload["lots"][0]


def test_move_into_washer_infers_giat_step(env):
    lot = _first_lot(env)
    moved = run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "washer-1")
    assert moved["lot"]["step"] == "giat"
    assert moved["lot"]["current_resource"] == "washer-1"
    # the original bin is freed, the washer is now busy
    res = {r["resource_id"]: r["status"] for r in run_json(env, "resource", "list")["resources"]}
    assert res["washer-1"] == "busy"
    assert res[lot["current_resource"]] == "free"


def test_move_into_bin_keeps_step(env):
    lot = _first_lot(env, phone="0905550001")
    run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "washer-2")
    moved = run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "bin-2")
    assert moved["lot"]["step"] == "giat"  # bin does not change the step
    assert moved["lot"]["current_resource"] == "bin-2"


def test_move_rejects_busy_target_without_force(env):
    a = _first_lot(env, phone="0905550002")
    b = _first_lot(env, phone="0905550003")
    run_json(env, "lot", "move", "--lot", a["lot_id"], "--to", "washer-5")
    r = run(env, "lot", "move", "--lot", b["lot_id"], "--to", "washer-5", "--json")
    assert r.returncode != 0
    assert "busy" in r.stderr
    ok = run(env, "lot", "move", "--lot", b["lot_id"], "--to", "washer-5", "--force", "--json")
    assert ok.returncode == 0


# ── counting + redo ──────────────────────────────────────────────────────────


def test_redo_sets_flag_and_moves_step_back(env):
    lot = _first_lot(env, phone="0906661111")
    run_json(env, "lot", "move", "--lot", lot["lot_id"], "--to", "dryer-1")  # step say
    redone = run_json(env, "lot", "redo", "--lot", lot["lot_id"], "--notes", "lem ban")
    assert redone["lot"]["is_redo"] is True
    assert redone["lot"]["step"] == "giat"  # default redo target


# ── deliver + cancel ─────────────────────────────────────────────────────────


def test_order_deliver_requires_all_counted(env):
    new = run_json(env, "order", "new", "--phone", "0907770000", "--bins", "1",
                   "--item", "khăn:100", "--item", "ga:50")
    oid = new["order"]["order_id"]
    # No types counted yet — blocked
    blocked = run(env, "order", "deliver", "--order", oid, "--json")
    assert blocked.returncode != 0
    assert "chưa đếm" in blocked.stderr
    # Count one type — still blocked
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "100")
    still_blocked = run(env, "order", "deliver", "--order", oid, "--json")
    assert still_blocked.returncode != 0
    # Count remaining type — now succeeds
    run_json(env, "order", "count", "--order", oid, "--type", "ga", "--counted", "50")
    ok = run_json(env, "order", "deliver", "--order", oid)
    assert ok["order"]["status"] == "done"


def test_lot_deliver_completes_order_when_last(env):
    new = run_json(env, "order", "new", "--phone", "0907771111", "--bins", "2",
                   "--item", "khăn:10")
    oid = new["order"]["order_id"]
    p1, p2 = new["lots"][0]["lot_id"], new["lots"][1]["lot_id"]
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "10")
    first = run_json(env, "lot", "deliver", "--lot", p1)
    assert first["order"]["status"] == "active"  # second lot still active
    last = run_json(env, "lot", "deliver", "--lot", p2)
    assert last["order"]["status"] == "done"


def test_cancel_frees_resources(env):
    new = run_json(env, "order", "new", "--phone", "0907772222", "--bins", "2")
    oid = new["order"]["order_id"]
    bins = [lot["current_resource"] for lot in new["lots"]]
    run_json(env, "order", "cancel", "--order", oid, "--reason", "khach huy")
    res = {r["resource_id"]: r["status"] for r in run_json(env, "resource", "list")["resources"]}
    assert all(res[b] == "free" for b in bins)
    assert run_json(env, "order", "show", "--order", oid)["order"]["status"] == "cancelled"


# ── customer history + dashboard ─────────────────────────────────────────────


def test_customer_history_groups_by_phone(env):
    run_json(env, "order", "new", "--phone", "0908880000", "--bins", "1")
    run_json(env, "order", "new", "--phone", "0908880000", "--bins", "1")
    run_json(env, "order", "new", "--phone", "0908889999", "--bins", "1")
    hist = run_json(env, "customer", "history", "--phone", "0908880000")
    assert len(hist["orders"]) == 2


def test_dashboard_payload_shape(env):
    new = run_json(env, "order", "new", "--phone", "0909990000", "--bins", "2")
    run_json(env, "lot", "move", "--lot", new["lots"][0]["lot_id"], "--to", "washer-1")
    dash = run_json(env, "dashboard")
    assert "resources" in dash and "orders" in dash and "steps" in dash
    assert len(dash["resources"]) == 37  # 15+10+10+1+1
    washer1 = next(r for r in dash["resources"] if r["resource_id"] == "washer-1")
    assert washer1["occupant"] is not None
    assert any(lot["lot_id"] == new["lots"][0]["lot_id"] for lot in dash["steps"]["giat"])


# ── data management ──────────────────────────────────────────────────────────


def test_resource_add_continues_index(env):
    added = run_json(env, "resource", "add", "--kind", "washer", "--count", "2")["added"]
    assert added == ["washer-11", "washer-12"]


def test_resource_retire_refuses_when_occupied(env):
    lot = run_json(env, "order", "new", "--phone", "0910000000", "--bins", "1")["lots"][0]
    busy_bin = lot["current_resource"]
    blocked = run(env, "resource", "retire", "--resource", busy_bin, "--json")
    assert blocked.returncode != 0
    ok = run(env, "resource", "retire", "--resource", "bin-15", "--json")
    assert ok.returncode == 0


def test_reset_clears_orders_and_reseeds_pool(env):
    run_json(env, "order", "new", "--phone", "0911111111", "--bins", "1")
    run_json(env, "data", "reset")
    assert run_json(env, "order", "list")["orders"] == []
    assert len(run_json(env, "resource", "list")["resources"]) == 37


def test_export_orders_json(env):
    run_json(env, "order", "new", "--phone", "0912222222", "--bins", "1")
    r = run(env, "data", "export", "--table", "orders", "--format", "json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert len(payload["orders"]) == 1


# ── move by physical resource (--from) ───────────────────────────────────────


def test_move_by_from_resource_resolves_lot(env):
    lot = _first_lot(env, phone="0905559999")
    bin_id = lot["current_resource"]
    moved = run_json(env, "lot", "move", "--from", bin_id, "--to", "washer-7")
    assert moved["lot"]["lot_id"] == lot["lot_id"]
    assert moved["lot"]["step"] == "giat"
    assert moved["lot"]["current_resource"] == "washer-7"


def test_move_from_empty_resource_errors(env):
    r = run(env, "lot", "move", "--from", "bin-14", "--to", "washer-8", "--json")
    assert r.returncode != 0
    assert "no active lot" in r.stderr


def test_move_requires_lot_or_from(env):
    r = run(env, "lot", "move", "--to", "washer-9", "--json")
    assert r.returncode != 0  # argparse: exactly one of --lot/--from is required


def test_move_from_ambiguous_errors(env):
    a = _first_lot(env, phone="0905558881")
    b = _first_lot(env, phone="0905558882")
    run_json(env, "lot", "move", "--lot", a["lot_id"], "--to", "washer-6")
    run_json(env, "lot", "move", "--lot", b["lot_id"], "--to", "washer-6", "--force")
    r = run(env, "lot", "move", "--from", "washer-6", "--to", "dryer-6", "--json")
    assert r.returncode != 0
    assert "multiple active lots" in r.stderr


# ── item accounting + reconciliation ─────────────────────────────────────────


def test_order_new_declares_item_lines(env):
    p = run_json(env, "order", "new", "--phone", "0901234567", "--bins", "2",
                 "--item", "khăn:100", "--item", "ga:50")
    types = {i["item_type"]: i["declared_qty"] for i in p["items"]}
    assert types == {"khăn": 100, "ga": 50}
    assert p["order"]["declared_total"] == 150


def test_order_new_rejects_bad_item(env):
    r = run(env, "order", "new", "--phone", "0900000000", "--bins", "1",
            "--item", "khăn:-10", "--json")
    assert r.returncode != 0
    r2 = run(env, "order", "new", "--phone", "0900000000", "--bins", "1",
             "--item", "khăn:abc", "--json")
    assert r2.returncode != 0


def test_order_count_by_type_updates_total(env):
    new = run_json(env, "order", "new", "--phone", "0902223334", "--bins", "1",
                   "--item", "khăn:100", "--item", "ga:50")
    oid = new["order"]["order_id"]
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "98")
    shown = run_json(env, "order", "show", "--order", oid)
    assert shown["order"]["total_items"] == 98  # only khăn counted so far
    khan = next(i for i in shown["order"]["items"] if i["item_type"] == "khăn")
    assert khan["counted_qty"] == 98 and khan["diff"] == -2


def test_order_count_unknown_type_errors(env):
    oid = run_json(env, "order", "new", "--phone", "0902223335", "--bins", "1",
                   "--item", "khăn:10")["order"]["order_id"]
    r = run(env, "order", "count", "--order", oid, "--type", "áo", "--counted", "5", "--json")
    assert r.returncode != 0


def test_reconcile_owed_and_extra(env):
    o1 = run_json(env, "order", "new", "--phone", "0905550000", "--bins", "1",
                  "--item", "khăn:100")["order"]["order_id"]
    run_json(env, "order", "count", "--order", o1, "--type", "khăn", "--counted", "98")
    o2 = run_json(env, "order", "new", "--phone", "0905550000", "--bins", "1",
                  "--item", "ga:20")["order"]["order_id"]
    run_json(env, "order", "count", "--order", o2, "--type", "ga", "--counted", "22")
    rec = run_json(env, "report", "reconcile", "--phone", "0905550000")
    c = rec["customers"][0]
    by = {i["item_type"]: i for i in c["items"]}
    assert by["khăn"]["owed"] == 2 and by["khăn"]["extra"] == 0
    assert by["ga"]["extra"] == 2 and by["ga"]["owed"] == 0
    assert c["owed_total"] == 2 and c["extra_total"] == 2


def test_deliver_requires_all_types_counted(env):
    new = run_json(env, "order", "new", "--phone", "0907770000", "--bins", "1",
                   "--item", "khăn:100", "--item", "ga:50")
    oid = new["order"]["order_id"]
    blocked = run(env, "order", "deliver", "--order", oid, "--json")
    assert blocked.returncode != 0 and "chưa đếm" in blocked.stderr
    run_json(env, "order", "count", "--order", oid, "--type", "khăn", "--counted", "100")
    run_json(env, "order", "count", "--order", oid, "--type", "ga", "--counted", "50")
    ok = run_json(env, "order", "deliver", "--order", oid)
    assert ok["order"]["status"] == "done"


def test_v2_migration_upgrades_v1_db(env, tmp_path):
    # Build a v1-shaped DB (no order_items / declared_total), then connect via the CLI.
    import sqlite3
    dbp = tmp_path / "v1.db"
    conn = sqlite3.connect(dbp)
    conn.executescript(
        "CREATE TABLE orders (order_id TEXT PRIMARY KEY, customer_phone TEXT NOT NULL, "
        "customer_name TEXT, status TEXT NOT NULL DEFAULT 'active', total_items INTEGER, "
        "note TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        "INSERT INTO orders VALUES ('DH-OLD-001','0900000000',NULL,'active',NULL,NULL,"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z');"
    )
    conn.commit()
    conn.close()
    e = dict(env)
    e["ATRIA_FLOW_DB"] = str(dbp)
    listed = run_json(e, "order", "list")
    assert any(o["order_id"] == "DH-OLD-001" for o in listed["orders"])  # no data loss
    # order_items table now usable
    assert run(e, "order", "new", "--phone", "0901111111", "--bins", "1",
               "--item", "khăn:5", "--json").returncode == 0
