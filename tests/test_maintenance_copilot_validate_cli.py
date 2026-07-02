"""Tests for `recommend-refs` and `validate` (in-memory Qdrant, temp audit)."""

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
    spec = importlib.util.spec_from_file_location("mc_validate_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_validate_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    out = []
    for t in texts:
        low = t.lower()
        out.append([1.0 if "gear" in low or "32" in low else 0.0,
                    1.0 if "door" in low or "52" in low else 0.0, 0.0])
    return out


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
    return mod


def test_recommend_refs_ranks_and_audits(cli, capsys, tmp_path):
    cli.main(["ingest"])
    capsys.readouterr()
    rc = cli.main(["recommend-refs", "landing gear removal", "--k", "3"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["query"] == "landing gear removal"
    assert len(out["recommendations"]) >= 1
    assert all("citation" in r and "confidence" in r for r in out["recommendations"])
    log = Path(str(tmp_path / "audit.jsonl")).read_text().splitlines()
    assert any(json.loads(x)["type"] == "recommend" for x in log)


def test_validate_marks_missing_ref_fail(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    payload = json.dumps({"defect": "gear indicator inop",
                          "cited_refs": ["MEL 32-30-01", "AMM 99-99-99"]})
    rc = cli.main(["validate", payload])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    by_ref = {r["ref"]: r for r in out["results"]}
    assert by_ref["MEL 32-30-01"]["status"] == "pass"
    assert by_ref["MEL 32-30-01"]["support"]
    assert by_ref["AMM 99-99-99"]["status"] == "fail"
