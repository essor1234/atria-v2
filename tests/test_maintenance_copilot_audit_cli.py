"""Tests for the `audit` CLI command (reads the JSONL trail, limits, JSON out)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_audit_cli_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_audit_cli_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    mod = _load_cli()
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("MC_AUDIT_LOG", str(log))
    return mod, str(log)


def test_audit_empty_when_no_log(cli, capsys):
    mod, _ = cli
    rc = mod.main(["audit"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"events": []}


def test_audit_returns_events_limited_and_ordered(cli, capsys):
    mod, log = cli
    # Seed three events directly through the audit module the CLI uses.
    for i in range(3):
        mod.audit.append_event({"type": "query", "n": i}, path=log)
    rc = mod.main(["audit", "--limit", "2"])
    assert rc == 0
    events = json.loads(capsys.readouterr().out)["events"]
    assert [e["n"] for e in events] == [1, 2]  # most recent two, in order
    assert all("ts" in e for e in events)
