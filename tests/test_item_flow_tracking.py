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
