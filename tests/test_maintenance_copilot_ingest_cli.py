# tests/test_maintenance_copilot_ingest_cli.py
"""Tests for the ingest/query CLI wiring (in-memory Qdrant, fake embeddings)."""

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
    spec = importlib.util.spec_from_file_location("mc_ingest_cli_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_ingest_cli_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    out = []
    for t in texts:
        low = t.lower()
        out.append([1.0 if "gear" in low else 0.0, 1.0 if "door" in low else 0.0,
                    1.0 if "brake" in low else 0.0])
    return out


@pytest.fixture()
def cli(monkeypatch):
    mod = _load_cli()
    from qdrant_client import QdrantClient
    shared = QdrantClient(":memory:")

    def fake_build_store(embed_fn=None, qdrant=None):
        store = mod.IndexStore(shared, _embed_fn)  # type: ignore[attr-defined]
        store.ensure_collection(dim=3)
        return store

    monkeypatch.setattr(mod, "_build_store", fake_build_store)
    return mod


def test_ingest_then_query_returns_cited_hits(cli, capsys):
    rc = cli.main(["ingest"])
    assert rc == 0
    ingest_out = json.loads(capsys.readouterr().out)
    assert ingest_out["documents"] == 4 and ingest_out["chunks"] >= 4

    rc = cli.main(["query", "main landing gear removal", "--k", "3", "--revision", "current"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["query"] == "main landing gear removal"
    assert len(out["hits"]) >= 1
    assert all("citation" in h for h in out["hits"])
    assert any(h["doc_type"] == "AMM" for h in out["hits"])


def test_query_ata_filter_narrows_results(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    cli.main(["query", "door panel", "--ata", "52", "--revision", "none"])
    out = json.loads(capsys.readouterr().out)
    assert len(out["hits"]) >= 1
    assert all(h["ata_chapter"] == "52" for h in out["hits"])


def test_reset_clears_index(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    rc = cli.main(["reset"])
    assert rc == 0
    reset_out = capsys.readouterr().out
    assert json.loads(reset_out)["reset"] is True
    cli.main(["query", "gear", "--revision", "none"])
    assert json.loads(capsys.readouterr().out)["hits"] == []


def test_list_and_index_alias(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()

    rc = cli.main(["list"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["count"] >= 1

    rc = cli.main(["index"])
    assert rc == 0
