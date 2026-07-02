"""Tests for the append-only JSONL audit trail with an injectable clock."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


def _fixed_now():
    return datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def test_append_then_read_roundtrip(tmp_path):
    a = _load("audit", "mc_audit_uut")
    log = str(tmp_path / "audit.log.jsonl")
    a.append_event({"type": "query", "text": "gear"}, path=log, now_fn=_fixed_now)
    a.append_event({"type": "recommend", "text": "brake"}, path=log, now_fn=_fixed_now)
    events = a.read_events(log)
    assert [e["type"] for e in events] == ["query", "recommend"]
    assert events[0]["ts"] == "2026-07-02T12:00:00+00:00"
    assert events[0]["text"] == "gear"


def test_read_missing_file_is_empty(tmp_path):
    a = _load("audit", "mc_audit_uut2")
    assert a.read_events(str(tmp_path / "nope.jsonl")) == []


def test_append_stamps_ts_and_returns_event(tmp_path):
    a = _load("audit", "mc_audit_uut3")
    log = str(tmp_path / "sub" / "audit.jsonl")   # parent dir must be created
    out = a.append_event({"type": "confirm"}, path=log, now_fn=_fixed_now)
    assert out["ts"] == "2026-07-02T12:00:00+00:00"
    assert Path(log).exists()
