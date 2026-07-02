"""Tests for the logistics module scripts (fleet, recommend, bans, bookings).

Each test runs the real module scripts as subprocesses against a *copy* of the
module (so the seeded CSVs are never mutated) and parses their JSON stdout.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_SRC = REPO_ROOT / "modules" / "logistics"


@pytest.fixture()
def module_dir(tmp_path: Path) -> Path:
    """A throwaway copy of modules/logistics so mutating ops stay isolated."""
    dst = tmp_path / "logistics"
    shutil.copytree(MODULE_SRC, dst)
    return dst


def run(module_dir: Path, script: str, *args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(module_dir / "scripts" / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload: dict = {}
    out = proc.stdout.strip()
    if out:
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = {"_raw": out}
    return proc.returncode, payload


# ---------------------------------------------------------------- fleet.py

def test_fleet_lookup_known_vehicle(module_dir: Path) -> None:
    code, data = run(module_dir, "fleet.py", "lookup", "--vehicle", "51C-123.45")
    assert code == 0
    assert data["found"] is True
    match = data["matches"][0]
    assert match["driver_name"] == "Nguyễn Văn An"
    assert match["ttdk_capacity"] == "4.9"
    assert match["source"] == "dki"


def test_fleet_lookup_loose_plate(module_dir: Path) -> None:
    # Dots/dashes/case should not matter.
    code, data = run(module_dir, "fleet.py", "lookup", "--vehicle", "51c12345")
    assert code == 0
    assert data["found"] is True


def test_fleet_lookup_missing(module_dir: Path) -> None:
    code, data = run(module_dir, "fleet.py", "lookup", "--vehicle", "00X-000.00")
    assert code == 1
    assert data["found"] is False


# ---------------------------------------------------------------- bans.py

def test_ban_hcm_inner_big_truck_daytime(module_dir: Path) -> None:
    # >2.5T banned 06:00-22:00 in HCM inner city; next window is the night.
    code, data = run(module_dir, "bans.py", "check",
                     "--zone", "Noi thanh HCM", "--time", "14:00", "--ttdk", "7.8")
    assert code == 0
    assert data["allowed"] is False
    assert data["next_allowed_window"] == "22:00-06:00"
    assert data["defer_to_next_day_suggested"] is True


def test_ban_bienhoa_49_allowed_afternoon(module_dir: Path) -> None:
    # TTĐK 4.9 (<=5) is not caught by the >5T rule; at 14:00 it's outside the
    # >2T ban windows (6-8, 11-13, 16-22) -> allowed. This is the truck the
    # manager says to use for a 5T Biên Hoà order.
    code, data = run(module_dir, "bans.py", "check",
                     "--zone", "Bien Hoa", "--time", "14:00", "--ttdk", "4.9")
    assert code == 0
    assert data["allowed"] is True
    assert data["must_exit_before"] == "16:00"


def test_ban_bienhoa_49_banned_morning(module_dir: Path) -> None:
    code, data = run(module_dir, "bans.py", "check",
                     "--zone", "Bien Hoa", "--time", "07:00", "--ttdk", "4.9")
    assert code == 0
    assert data["allowed"] is False


def test_ban_diacritic_insensitive(module_dir: Path) -> None:
    code_a, data_a = run(module_dir, "bans.py", "check",
                         "--zone", "Bien Hoa", "--time", "14:00", "--ttdk", "4.9")
    code_b, data_b = run(module_dir, "bans.py", "check",
                         "--zone", "Biên Hoà", "--time", "14:00", "--ttdk", "4.9")
    assert code_a == code_b == 0
    assert data_a["allowed"] == data_b["allowed"]
    assert data_a["zone_matched"] == data_b["zone_matched"]


def test_ban_unknown_zone_warns(module_dir: Path) -> None:
    code, data = run(module_dir, "bans.py", "check",
                     "--zone", "Phú Quốc", "--time", "10:00", "--ttdk", "5")
    assert code == 0
    assert data["allowed"] is True
    assert "warning" in data


# ---------------------------------------------------------------- recommend.py

def test_recommend_surfaces_boundary_truck(module_dir: Path) -> None:
    # 5T order to Biên Hoà at 14:00: the 4.9T truck must be recommended, and the
    # bigger trucks (TTĐK > 5) must be flagged banned at that time.
    code, data = run(module_dir, "recommend.py", "match",
                     "--weight", "5", "--cbm", "18", "--zone", "Bien Hoa", "--time", "14:00")
    assert code == 0
    assert "51C-123.45" in data["recommended"]
    by_plate = {c["vehicle_number"]: c for c in data["candidates"]}
    assert by_plate["51C-123.45"]["capacity_fit"] == "near_boundary"
    assert "ban_tradeoff_candidate" in by_plate["51C-123.45"]["flags"]
    # A 15T truck (TTĐK 14.5 > 5) is banned in Biên Hoà at 14:00.
    assert "banned_at_time" in by_plate["51C-456.78"]["flags"]


def test_recommend_upsell_flag_on_big_truck(module_dir: Path) -> None:
    code, data = run(module_dir, "recommend.py", "match",
                     "--weight", "8", "--cbm", "28", "--new-customer")
    assert code == 0
    by_plate = {c["vehicle_number"]: c for c in data["candidates"]}
    big = by_plate["51C-456.78"]  # 15T ISUZU
    assert "upsell_bigger_truck" in big["flags"]
    assert big["upsell"]["use_pct_limit"] == 80
    assert big["upsell"]["new_customer_only"] is True


def test_recommend_cbm_insufficient(module_dir: Path) -> None:
    # 3.5T VINHPHAT = 16 CBM; asking for 18 CBM should mark it insufficient.
    code, data = run(module_dir, "recommend.py", "match", "--weight", "1.5", "--cbm", "18")
    assert code == 0
    by_plate = {c["vehicle_number"]: c for c in data["candidates"]}
    assert by_plate["51C-234.56"]["cbm_fit"] == "insufficient"


# ---------------------------------------------------------------- bookings.py

def test_booking_multi_truck_roundtrip(module_dir: Path) -> None:
    code, created = run(module_dir, "bookings.py", "create",
                        "--customer", "Hoà Phát", "--destination", "Bien Hoa", "--weight", "5")
    assert code == 0
    bid = created["created"]

    code, _ = run(module_dir, "bookings.py", "add-truck",
                  "--booking", bid, "--vehicle", "51C-123.45", "--delivery-time", "14:00")
    assert code == 0
    code, _ = run(module_dir, "bookings.py", "add-truck",
                  "--booking", bid, "--vehicle", "51D33344", "--delivery-time", "14:30")
    assert code == 0

    code, listing = run(module_dir, "bookings.py", "list", "--json")
    assert code == 0
    booking = next(b for b in listing["bookings"] if b["booking_id"] == bid)
    assert len(booking["trucks"]) == 2
    plates = {t["vehicle_number"] for t in booking["trucks"]}
    assert plates == {"51C-123.45", "51D-333.44"}

    code, _ = run(module_dir, "bookings.py", "set-status", "--booking", bid, "--status", "confirmed")
    assert code == 0
    code, removed = run(module_dir, "bookings.py", "remove", "--booking", bid)
    assert code == 0
    assert removed["removed"] == bid


def test_booking_add_unknown_vehicle_fails(module_dir: Path) -> None:
    code, created = run(module_dir, "bookings.py", "create",
                        "--customer", "X", "--destination", "Tan Binh", "--weight", "2")
    bid = created["created"]
    code, _ = run(module_dir, "bookings.py", "add-truck",
                  "--booking", bid, "--vehicle", "99X-000.00")
    assert code == 1


# ---------------------------------------------------------------- notify.py

def test_notify_dry_run_composes_owner_message(module_dir: Path) -> None:
    # Build a confirmed booking, then dry-run the owner Zalo notification.
    code, created = run(module_dir, "bookings.py", "create",
                        "--customer", "Electrolux", "--destination", "Bien Hoa", "--weight", "5")
    assert code == 0
    bid = created["created"]
    code, _ = run(module_dir, "bookings.py", "add-truck",
                  "--booking", bid, "--vehicle", "51C-123.45", "--delivery-time", "14:00")
    assert code == 0

    # Explicit --dry-run forces compose-only (no network) regardless of env creds.
    code, data = run(module_dir, "notify.py", "send", "--booking", bid, "--dry-run")
    assert code == 0
    assert data["mode"] == "dry-run"
    assert data["booking_id"] == bid
    assert bid in data["message"]
    assert "Electrolux" in data["message"]
    assert "51C-123.45" in data["message"]
    assert "Nguyễn Văn An" in data["message"]


def test_notify_dry_run_when_no_owner_configured(module_dir: Path) -> None:
    # With no --dry-run flag but ZALO_OWNER_USER_ID unset, send must still be a
    # safe no-op dry-run (never an accidental live send).
    code, created = run(module_dir, "bookings.py", "create",
                        "--customer", "Pana", "--destination", "Tan Binh", "--weight", "2")
    bid = created["created"]
    code, data = run(module_dir, "notify.py", "send", "--booking", bid)
    assert code == 0
    assert data["mode"] == "dry-run"


def test_notify_missing_booking(module_dir: Path) -> None:
    code, data = run(module_dir, "notify.py", "send", "--booking", "BK-9999", "--dry-run")
    assert code == 1
    assert "not found" in data["error"]
