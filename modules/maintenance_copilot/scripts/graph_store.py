# modules/maintenance_copilot/scripts/graph_store.py
"""Neo4j-backed knowledge graph store.

All database access goes through an injected ``run_fn(cypher, params) -> rows``,
so unit tests can supply a fake and never touch a server. The production
``run_fn`` (``neo4j_run_fn``) opens a session per call against a Neo4j driver.

Node labels are the entity type; nodes and edges are matched/merged by ``key``.
Every write carries the extraction's stamped props (provenance, confidence,
status), so an LLM-built edge stays ``unverified`` until an engineer confirms it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extraction import (  # type: ignore[import-not-found]
    ALLOWED_EDGE_TYPES,
    ALLOWED_ENTITY_TYPES,
    GraphExtraction,
)

RunFn = Callable[[str, dict], list]


class GraphStore:
    """Create constraints, upsert extractions, and query the graph."""

    def __init__(self, run_fn: RunFn):
        self._run = run_fn

    def ensure_constraints(self) -> None:
        """One uniqueness constraint on ``key`` per allowed entity label."""
        for label in sorted(ALLOWED_ENTITY_TYPES):
            self._run(
                f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.key IS UNIQUE",
                {},
            )

    def upsert_extraction(self, ext: GraphExtraction) -> tuple[int, int]:
        """MERGE every node and edge; return (node_count, edge_count)."""
        for ent in ext.entities:
            self._run(
                f"MERGE (n:{ent.type} {{key: $key}}) SET n += $props",
                {"key": ent.key, "props": ent.props},
            )
        for edge in ext.edges:
            self._run(
                "MATCH (a {key: $src_key}), (b {key: $dst_key}) "
                f"MERGE (a)-[r:{edge.type}]->(b) SET r += $props",
                {"src_key": edge.src_key, "dst_key": edge.dst_key, "props": edge.props},
            )
        return len(ext.entities), len(ext.edges)

    def neighbors(self, entity_key: str, hops: int = 1) -> list[dict]:
        """Return entities reachable from ``entity_key`` within ``hops`` hops.

        Note: for hops>1 the returned ``status``/``edge_type`` describe only the
        terminal edge of the path, so a multi-hop result may traverse an unverified
        intermediate edge — callers must not treat a multi-hop link as fully verified.
        """
        depth = max(1, int(hops))
        cypher = (
            f"MATCH (a {{key: $key}})-[r*1..{depth}]-(b) "
            "RETURN DISTINCT b.key AS neighbor_key, labels(b) AS neighbor_labels, "
            "type(last(r)) AS edge_type, last(r).status AS status, "
            "last(r).confidence AS confidence"
        )
        return self._run(cypher, {"key": entity_key})

    def confirm_edge(self, src_key: str, edge_type: str, dst_key: str) -> int:
        """Flip an edge's status to engineer_confirmed; return rows updated."""
        if edge_type not in ALLOWED_EDGE_TYPES:
            raise ValueError(f"unknown edge type: {edge_type!r}")
        cypher = (
            "MATCH (a {key: $src_key})-[r:" + edge_type + "]->(b {key: $dst_key}) "
            "SET r.status = 'engineer_confirmed' RETURN count(r) AS updated"
        )
        rows = self._run(cypher, {"src_key": src_key, "dst_key": dst_key})
        return int(rows[0]["updated"]) if rows else 0

    def stats(self) -> dict:
        """Return node/edge counts and the number of unverified edges."""
        rows = self._run(
            "MATCH (n) WITH count(n) AS nodes "
            "OPTIONAL MATCH ()-[r]->() "
            "RETURN nodes, count(r) AS edges, "
            "sum(CASE WHEN r.status='unverified' THEN 1 ELSE 0 END) AS unverified_edges",
            {},
        )
        if not rows:
            return {"nodes": 0, "edges": 0, "unverified_edges": 0}
        row = rows[0]
        return {
            "nodes": row.get("nodes", 0),
            "edges": row.get("edges", 0),
            "unverified_edges": row.get("unverified_edges", 0),
        }

    def reset(self) -> None:
        """Delete all nodes and relationships."""
        self._run("MATCH (n) DETACH DELETE n", {})


def neo4j_run_fn(driver) -> RunFn:
    """Build a run_fn that executes each statement in its own Neo4j session."""

    def _run(cypher: str, params: dict) -> list:
        with driver.session() as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    return _run
