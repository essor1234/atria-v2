"""Tests for `query --synthesize` wiring (in-memory Qdrant, fake chat, temp audit)."""

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
    spec = importlib.util.spec_from_file_location("mc_query_synth_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_query_synth_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    return [[1.0 if "gear" in t.lower() else 0.0, 0.0, 0.0] for t in texts]


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    mod = _load_cli()
    from qdrant_client import QdrantClient
    shared = QdrantClient(":memory:")
    monkeypatch.setenv("MC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

    def fake_store(embed_fn=None, qdrant=None):
        s = mod.IndexStore(shared, _embed_fn)
        s.ensure_collection(dim=3)
        return s

    monkeypatch.setattr(mod, "_build_store", fake_store)
    monkeypatch.setattr(mod, "_synthesis_chat_fn",
                        lambda: (lambda messages: "Gear removal per AMM [amm_ata32#0]."))
    return mod, str(tmp_path / "audit.jsonl")


def test_query_synthesize_attaches_answer_and_audits(cli, capsys):
    mod, audit_log = cli
    mod.main(["ingest"])
    capsys.readouterr()
    rc = mod.main(["query", "gear removal", "--revision", "none", "--synthesize"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "answer" in out
    assert "disclaimer" in out["answer"]
    # An audit event was recorded.
    from importlib import import_module  # noqa: F401
    lines = Path(audit_log).read_text(encoding="utf-8").splitlines()
    assert any(json.loads(ln)["type"] == "query" for ln in lines)


def test_query_without_synthesize_has_no_answer(cli, capsys):
    mod, _ = cli
    mod.main(["ingest"])
    capsys.readouterr()
    mod.main(["query", "gear", "--revision", "none"])
    out = json.loads(capsys.readouterr().out)
    assert "answer" not in out
