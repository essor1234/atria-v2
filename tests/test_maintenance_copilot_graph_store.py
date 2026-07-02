# tests/test_maintenance_copilot_graph_store.py
"""Tests for the Neo4j graph store using a fake in-memory run_fn (no server)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeRunner:
    """Captures every (cypher, params) call; returns canned rows when configured."""

    def __init__(self, rows=None):
        self.calls = []
        self._rows = rows or []

    def __call__(self, cypher, params):
        self.calls.append((cypher, params))
        return self._rows


def _extraction(extraction_mod):
    prov = {"source_doc": "mel_ata32.md", "revision": "Rev-18",
            "page": "mel_ata32#0", "extracted_by": "m"}
    ent = extraction_mod.Entity("MELItem", "32-30-01",
                                {**prov, "status": "unverified", "confidence": 0.9})
    ata = extraction_mod.Entity("ATAChapter", "32",
                                {**prov, "status": "unverified", "confidence": 0.9})
    edge = extraction_mod.Edge("IN_CHAPTER", "32-30-01", "32",
                               {**prov, "status": "unverified", "confidence": 0.9})
    return extraction_mod.GraphExtraction([ent, ata], [edge])


def test_upsert_merges_nodes_and_edges_with_props():
    extraction = _load("extraction", "mc_extraction_for_graph")
    graph_store = _load("graph_store", "mc_graph_store_uut")
    runner = _FakeRunner()
    store = graph_store.GraphStore(runner)
    nodes, edges = store.upsert_extraction(_extraction(extraction))
    assert (nodes, edges) == (2, 1)
    # Every node MERGE carries a $props dict with status + confidence.
    merges = [c for c in runner.calls if "MERGE" in c[0]]
    assert any(c[1].get("props", {}).get("status") == "unverified" for c in merges)
    # The edge MERGE references the MELItem/ATAChapter keys.
    edge_calls = [c for c in runner.calls if "IN_CHAPTER" in c[0]]
    assert edge_calls and edge_calls[0][1]["src_key"] == "32-30-01"
    assert edge_calls[0][1]["dst_key"] == "32"


def test_neighbors_returns_rows_from_runner():
    _load("extraction", "mc_extraction_for_graph2")
    graph_store = _load("graph_store", "mc_graph_store_uut2")
    rows = [{"neighbor_key": "32", "neighbor_labels": ["ATAChapter"],
             "edge_type": "IN_CHAPTER", "status": "unverified", "confidence": 0.9}]
    runner = _FakeRunner(rows=rows)
    store = graph_store.GraphStore(runner)
    out = store.neighbors("32-30-01", hops=1)
    assert out == rows
    assert "MATCH" in runner.calls[0][0]
    assert runner.calls[0][1]["key"] == "32-30-01"


def test_confirm_edge_sets_status_and_counts():
    _load("extraction", "mc_extraction_for_graph3")
    graph_store = _load("graph_store", "mc_graph_store_uut3")
    runner = _FakeRunner(rows=[{"updated": 1}])
    store = graph_store.GraphStore(runner)
    n = store.confirm_edge("32-30-01", "IN_CHAPTER", "32")
    assert n == 1
    assert "engineer_confirmed" in runner.calls[0][0]
    assert runner.calls[0][1] == {"src_key": "32-30-01", "dst_key": "32"}


def test_confirm_edge_rejects_unknown_edge_type():
    import pytest
    _load("extraction", "mc_extraction_for_graph4")
    graph_store = _load("graph_store", "mc_graph_store_uut4")
    runner = _FakeRunner(rows=[{"updated": 1}])
    store = graph_store.GraphStore(runner)
    with pytest.raises(ValueError, match="unknown edge type"):
        store.confirm_edge("a", "NOT_A_REAL_TYPE", "b")
    # Valid edge type must still work
    n = store.confirm_edge("32-30-01", "IN_CHAPTER", "32")
    assert n == 1


def test_stats_returns_row_when_edges_zero():
    # Tests the row-handling branch: runner returns a row with edges=0 (as
    # OPTIONAL MATCH in production would produce).  The OPTIONAL MATCH behavior
    # itself (no rows → zero edges) is validated in the deferred live e2e suite.
    _load("extraction", "mc_extraction_for_graph5")
    graph_store = _load("graph_store", "mc_graph_store_uut5")
    canned = [{"nodes": 3, "edges": 0, "unverified_edges": 0}]
    runner = _FakeRunner(rows=canned)
    store = graph_store.GraphStore(runner)
    result = store.stats()
    assert result == {"nodes": 3, "edges": 0, "unverified_edges": 0}


def test_stats_empty_rows_returns_zero_dict():
    # Tests the fallback branch: runner returns [] (empty result from Neo4j).
    _load("extraction", "mc_extraction_for_graph6")
    graph_store = _load("graph_store", "mc_graph_store_uut6")
    runner = _FakeRunner(rows=[])
    store = graph_store.GraphStore(runner)
    result = store.stats()
    assert result == {"nodes": 0, "edges": 0, "unverified_edges": 0}
