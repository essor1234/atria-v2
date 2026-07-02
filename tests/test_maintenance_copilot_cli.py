"""Tests for the maintenance_copilot CLI (health command)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_cli_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["mc_cli_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_check_health_reports_ok_and_errors():
    mod = _load_cli()

    def good():
        return None

    def bad():
        raise RuntimeError("boom")

    result = mod.check_health({"tei": good, "qdrant": bad})
    assert result["tei"] == "ok"
    assert result["qdrant"].startswith("error:")
    assert "boom" in result["qdrant"]


def test_main_health_exit_code_and_json(monkeypatch, capsys):
    mod = _load_cli()
    # Force all probes to succeed by patching the probe builder.
    monkeypatch.setattr(mod, "_build_probes", lambda: {"tei": lambda: None,
                                                       "qdrant": lambda: None,
                                                       "neo4j": lambda: None,
                                                       "llm": lambda: None})
    rc = mod.main(["health"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert all(v == "ok" for v in payload.values())


def test_main_health_fails_when_a_probe_errors(monkeypatch, capsys):
    mod = _load_cli()
    monkeypatch.setattr(mod, "_build_probes", lambda: {"tei": lambda: None,
                                                       "qdrant": (lambda: (_ for _ in ()).throw(RuntimeError("x")))})
    rc = mod.main(["health"])
    assert rc == 1
