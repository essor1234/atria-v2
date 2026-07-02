"""Tests for --graph multi-hop context attached to query results."""

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
    spec = importlib.util.spec_from_file_location("mc_query_graph_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_query_graph_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    return [[1.0 if "gear" in t.lower() else 0.0, 0.0, 0.0] for t in texts]


@pytest.fixture()
def cli(monkeypatch):
    mod = _load_cli()
    from qdrant_client import QdrantClient
    shared = QdrantClient(":memory:")

    def fake_store(embed_fn=None, qdrant=None):
        s = mod.IndexStore(shared, _embed_fn)
        s.ensure_collection(dim=3)
        return s

    class _FakeGraph:
        def neighbors(self, key, hops=1):
            return [{"neighbor_key": "32-30-01", "neighbor_labels": ["MELItem"],
                     "edge_type": "IN_CHAPTER", "status": "unverified", "confidence": 0.9}]

    monkeypatch.setattr(mod, "_build_store", fake_store)
    monkeypatch.setattr(mod, "_build_graph_store", lambda run_fn=None: _FakeGraph())
    return mod


def test_query_without_graph_flag_has_no_graph_context(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    cli.main(["query", "gear", "--revision", "none"])
    out = json.loads(capsys.readouterr().out)
    assert "graph_context" not in out


def test_query_with_graph_flag_attaches_related(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    cli.main(["query", "gear removal", "--ata", "32", "--revision", "none", "--graph"])
    out = json.loads(capsys.readouterr().out)
    assert out["graph_context"]["ata_chapter"] == "32"
    assert out["graph_context"]["related"][0]["neighbor_key"] == "32-30-01"
    assert out["graph_context"]["related"][0]["status"] == "unverified"
