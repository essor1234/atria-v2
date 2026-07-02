# tests/test_maintenance_copilot_index_store.py
"""Tests for the Qdrant-backed index store (real in-memory Qdrant, fake embeddings)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name: str, sentinel: str):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


def _rec(chunking, chunk_id, text, revision="Rev-42", ata="32", doc_type="AMM"):
    return chunking.ChunkRecord(
        chunk_id=chunk_id, text=text, start_index=0, end_index=len(text),
        token_count=len(text.split()), doc_type=doc_type, title="T",
        revision=revision, ata_chapter=ata, source_path=f"/x/{chunk_id}.md",
        citation=f"{doc_type} T ({revision}) · {chunk_id}",
    )


def _embed_fn(texts):
    # Deterministic 3-dim vectors: keyword presence for "gear"/"door"/"brake".
    out = []
    for t in texts:
        low = t.lower()
        out.append([
            1.0 if "gear" in low else 0.0,
            1.0 if "door" in low else 0.0,
            1.0 if "brake" in low else 0.0,
        ])
    return out


@pytest.fixture()
def store():
    from qdrant_client import QdrantClient
    chunking = _load("chunking", "mc_chunking_for_store")
    index_store = _load("index_store", "mc_index_store_uut")
    s = index_store.IndexStore(QdrantClient(":memory:"), _embed_fn)
    s.ensure_collection(dim=3)
    return s, chunking, index_store


def test_upsert_then_query_ranks_relevant_chunk_first(store):
    s, chunking, _ = store
    n = s.upsert_chunks([
        _rec(chunking, "amm_ata32#0", "Main landing gear removal"),
        _rec(chunking, "cdl_ata52#0", "Access door panel missing", ata="52", doc_type="CDL"),
    ])
    assert n == 2
    hits = s.query("gear leg", k=1, revision=None)
    assert len(hits) == 1
    assert hits[0]["chunk_id"] == "amm_ata32#0"
    assert hits[0]["citation"].startswith("AMM T (Rev-42)")


def test_query_filters_by_ata_chapter(store):
    s, chunking, _ = store
    s.upsert_chunks([
        _rec(chunking, "amm_ata32#0", "gear removal"),
        _rec(chunking, "cdl_ata52#0", "door panel", ata="52", doc_type="CDL"),
    ])
    hits = s.query("door", k=5, ata_chapter="52", revision=None)
    assert [h["chunk_id"] for h in hits] == ["cdl_ata52#0"]


def test_query_current_revision_excludes_superseded(store):
    s, chunking, _ = store
    s.upsert_chunks([
        _rec(chunking, "amm_old#0", "gear removal old", revision="Rev-41"),
        _rec(chunking, "amm_new#0", "gear removal new", revision="Rev-42"),
    ])
    hits = s.query("gear", k=5, revision="current")
    ids = [h["chunk_id"] for h in hits]
    assert "amm_new#0" in ids and "amm_old#0" not in ids
