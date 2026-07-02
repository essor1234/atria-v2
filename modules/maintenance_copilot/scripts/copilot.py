#!/usr/bin/env python
"""maintenance_copilot CLI.

Phase 1 ships the ``health`` subcommand: it verifies the four local sidecars
(TEI embeddings, Qdrant, Neo4j, local LLM) are reachable. Later phases add
``ingest``, ``index``, ``graph``, ``query``, ``validate``, and ``check``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RoleConfig, load_config  # type: ignore[import-not-found]
from client import RoleClient  # type: ignore[import-not-found]
from corpus import load_corpus  # type: ignore[import-not-found]
from chunking import chunk_document  # type: ignore[import-not-found]
from index_store import IndexStore  # type: ignore[import-not-found]
from extraction import extract_graph  # type: ignore[import-not-found]
from graph_store import GraphStore, neo4j_run_fn  # type: ignore[import-not-found]
import audit  # type: ignore[import-not-found]

# Output dimension of the deployed TEI embedding model (Qwen3-Embedding-0.6B).
# Must match the model configured for the index_embed role.
EMBED_DIM = 1024


def _samples_dir() -> str:
    return str(Path(__file__).resolve().parent.parent / "sample_manuals")


def _build_store(
    embed_fn: Callable | None = None, qdrant: object | None = None
) -> IndexStore:
    """Build an IndexStore from MC_QDRANT_URL + a RoleClient index_embed embedder.

    Args:
        embed_fn: Optional embedding callable; defaults to RoleClient index_embed.
        qdrant: Optional QdrantClient instance; defaults to MC_QDRANT_URL.

    Returns:
        An :class:`IndexStore` with its collection ensured.
    """
    from qdrant_client import QdrantClient

    if qdrant is None:
        qdrant = QdrantClient(url=_env("MC_QDRANT_URL", "http://localhost:6333"))
    if embed_fn is None:
        rc = RoleClient(load_config())
        embed_fn = lambda texts: rc.embed("index_embed", texts)  # noqa: E731
    store = IndexStore(qdrant, embed_fn)
    store.ensure_collection(dim=EMBED_DIM)
    return store


def check_health(probes: dict[str, Callable[[], None]]) -> dict[str, str]:
    """Run each probe; map name -> 'ok' or 'error: <message>'.

    Args:
        probes: Mapping of probe name to zero-argument callable. Each callable
            should raise on failure and return None on success.

    Returns:
        Dict mapping each probe name to ``"ok"`` or ``"error: <message>"``.
        Never raises — all exceptions are caught and recorded as errors.
    """
    out: dict[str, str] = {}
    for name, probe in probes.items():
        try:
            probe()
            out[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - health must never raise
            out[name] = f"error: {exc}"
    return out


def _build_probes() -> dict[str, Callable[[], None]]:
    """Build live probes against the configured sidecars."""
    cfg: dict[str, RoleConfig] = load_config()
    rc = RoleClient(cfg)

    def tei_probe() -> None:
        rc.embed("index_embed", ["ping"])

    def llm_probe() -> None:
        rc.chat("synthesis", [{"role": "user", "content": "ping"}], max_tokens=1)

    def qdrant_probe() -> None:
        from qdrant_client import QdrantClient  # local import: optional dep

        url = _env("MC_QDRANT_URL", "http://localhost:6333")
        QdrantClient(url=url).get_collections()

    def neo4j_probe() -> None:
        from neo4j import GraphDatabase  # local import: optional dep

        uri = _env("MC_NEO4J_URI", "bolt://localhost:7687")
        user = _env("MC_NEO4J_USER", "neo4j")
        pwd = _env("MC_NEO4J_PASSWORD", "atria-neo4j")
        driver = GraphDatabase.driver(uri, auth=(user, pwd))
        try:
            driver.verify_connectivity()
        finally:
            driver.close()

    return {"tei": tei_probe, "llm": llm_probe,
            "qdrant": qdrant_probe, "neo4j": neo4j_probe}


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _kg_chat_fn() -> Callable[[list], str]:
    """Return a chat callable bound to the kg_extract role."""
    rc = RoleClient(load_config())
    return lambda messages: rc.chat("kg_extract", messages)


def _synthesis_chat_fn() -> Callable[[list], str]:
    """Return a chat callable bound to the synthesis role."""
    rc = RoleClient(load_config())
    return lambda messages: rc.chat("synthesis", messages)


def _build_graph_store(run_fn: Callable | None = None) -> GraphStore:
    """Build a GraphStore from MC_NEO4J_* env (or an injected run_fn) + constraints.

    Args:
        run_fn: Optional Neo4j run callable; defaults to one built from MC_NEO4J_* env vars.

    Returns:
        A :class:`GraphStore` with constraints ensured.
    """
    if run_fn is None:
        from neo4j import GraphDatabase  # local import: optional dep

        driver = GraphDatabase.driver(
            _env("MC_NEO4J_URI", "bolt://localhost:7687"),
            auth=(_env("MC_NEO4J_USER", "neo4j"), _env("MC_NEO4J_PASSWORD", "atria-neo4j")),
        )
        run_fn = neo4j_run_fn(driver)
    store = GraphStore(run_fn)
    store.ensure_constraints()
    return store


def _cmd_graph_build(samples: str) -> int:
    """Extract knowledge-graph triples from corpus chunks and upsert into the graph store.

    Args:
        samples: Path to the corpus directory.

    Returns:
        ``0`` on success.
    """
    store = _build_graph_store()
    chat_fn = _kg_chat_fn()
    docs = load_corpus(samples)
    kg_model = load_config()["kg_extract"].model
    chunks = nodes = edges = 0
    for doc in docs:
        for rec in chunk_document(doc):
            chunks += 1
            prov = {
                "source_doc": Path(rec.source_path).name,
                "revision": rec.revision,
                "page": rec.chunk_id,
                "extracted_by": kg_model,
            }
            ext = extract_graph(rec.text, chat_fn, prov)
            n, e = store.upsert_extraction(ext)
            nodes += n
            edges += e
    print(json.dumps({"chunks": chunks, "nodes": nodes, "edges": edges}, indent=2))
    return 0


def _cmd_graph_show(key: str, hops: int) -> int:
    """Show neighbors of an entity, flagging unverified edges.

    Args:
        key: Entity key to look up.
        hops: Number of hops to traverse.

    Returns:
        ``0`` on success.
    """
    store = _build_graph_store()
    rows = store.neighbors(key, hops=hops)
    unverified = sum(1 for r in rows if r.get("status") == "unverified")
    print(json.dumps({"key": key, "neighbors": rows, "unverified": unverified}, indent=2))
    return 0


def _cmd_graph_confirm(src: str, edge_type: str, dst: str) -> int:
    """Mark an edge as engineer_confirmed.

    Args:
        src: Source entity key.
        edge_type: Edge type label.
        dst: Destination entity key.

    Returns:
        ``0`` on success.
    """
    store = _build_graph_store()
    print(json.dumps({"confirmed": store.confirm_edge(src, edge_type, dst)}, indent=2))
    return 0


def _cmd_graph_stats() -> int:
    """Print graph node/edge counts.

    Returns:
        ``0`` on success.
    """
    print(json.dumps(_build_graph_store().stats(), indent=2))
    return 0


def _cmd_graph_reset() -> int:
    """Delete all graph data and print confirmation.

    Returns:
        ``0`` on success.
    """
    _build_graph_store().reset()
    print(json.dumps({"reset": True}, indent=2))
    return 0


def _cmd_ingest(samples: str) -> int:
    """Parse + chunk + upsert the corpus from *samples* dir.

    Args:
        samples: Path to the corpus directory.

    Returns:
        ``0`` on success.
    """
    store = _build_store()
    docs = load_corpus(samples)
    total = 0
    for doc in docs:
        total += store.upsert_chunks(chunk_document(doc))
    print(json.dumps({"documents": len(docs), "chunks": total}, indent=2))
    return 0


def _cmd_query(text: str, k: int, ata: str | None, revision: str,
               with_graph: bool = False, synthesize: bool = False) -> int:
    """Retrieve top cited passages for *text*.

    Args:
        text: Query string.
        k: Maximum number of hits.
        ata: Optional ATA chapter filter.
        revision: Revision filter string, or ``"none"`` to disable.
        with_graph: When ``True``, attach related knowledge-graph entities for the
            top hit's ATA chapter (or ``ata`` if provided). Requires Neo4j.
        synthesize: When ``True``, compose a cited answer and append an audit event.

    Returns:
        ``0`` on success.
    """
    rev: str | None = None if revision.lower() == "none" else revision
    store = _build_store()
    hits = store.query(text, k=k, ata_chapter=ata, revision=rev)
    payload: dict[str, object] = {"query": text, "hits": hits}
    if with_graph and hits:
        chapter = ata or hits[0].get("ata_chapter")
        related = _build_graph_store().neighbors(chapter, hops=1) if chapter else []
        payload["graph_context"] = {"ata_chapter": chapter, "related": related}
    if synthesize:
        answer = synthesize_answer(text, hits)
        payload["answer"] = answer
        audit.append_event({"type": "query", "query": text,
                            "citations": answer["citations"],
                            "needs_review": answer["needs_review"]})
    print(json.dumps(payload, indent=2))
    return 0


def synthesize_answer(text: str, hits: list) -> dict:
    """Synthesize a cited answer for ``text`` over ``hits`` via the synthesis role."""
    from synthesis import synthesize as _synth  # local alias to avoid shadowing

    return _synth(text, hits, _synthesis_chat_fn())


def _read_json_arg(value: str) -> dict:
    """Parse a JSON string, or read JSON from stdin when value == '-'.

    Args:
        value: A JSON string, or ``"-"`` to read from stdin.

    Returns:
        Parsed JSON as a dict.
    """
    if value == "-":
        value = sys.stdin.read()
    return json.loads(value)


def _cmd_recommend_refs(text: str, k: int) -> int:
    """Retrieve top-k refs for *text* and print ranked recommendations.

    Args:
        text: Natural-language defect description to query.
        k: Maximum number of recommendations to return.

    Returns:
        ``0`` on success.
    """
    store = _build_store()
    hits = store.query(text, k=k, revision="current")
    recs = [
        {"citation": h["citation"], "chunk_id": h["chunk_id"], "doc_type": h["doc_type"],
         "revision": h["revision"], "confidence": h["score"]}
        for h in hits
    ]
    audit.append_event({"type": "recommend", "query": text,
                        "citations": [r["chunk_id"] for r in recs]})
    print(json.dumps({"query": text, "recommendations": recs}, indent=2))
    return 0


def _cmd_validate(raw: str) -> int:
    """Validate cited refs against approved docs in the index.

    Args:
        raw: JSON string (or ``"-"`` for stdin) with ``defect`` and ``cited_refs`` keys.

    Returns:
        ``0`` on success.
    """
    data = _read_json_arg(raw)
    store = _build_store()
    results = []
    for ref in data.get("cited_refs", []):
        token = ref.split()[-1].lower() if ref.split() else ref.lower()
        hits = store.query(ref, k=3, revision="current")
        support = None
        for h in hits:
            if token in h["citation"].lower() or token in h["text"].lower():
                support = h["citation"]
                break
        results.append({"ref": ref, "status": "pass" if support else "fail",
                        "support": support})
    audit.append_event({"type": "validate", "refs": data.get("cited_refs", []),
                        "results": results})
    print(json.dumps({"defect": data.get("defect", ""), "results": results}, indent=2))
    return 0


def _cmd_list() -> int:
    """Print index stats as JSON.

    Returns:
        ``0`` on success.
    """
    print(json.dumps(_build_store().list_indexed(), indent=2))
    return 0


def _cmd_reset() -> int:
    """Drop the Qdrant collection and print confirmation.

    Returns:
        ``0`` on success.
    """
    _build_store().reset()
    print(json.dumps({"reset": True}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` with ``health``, ``ingest``,
        ``index``, ``query``, ``list``, and ``reset`` subcommands registered.
    """
    parser = argparse.ArgumentParser(prog="copilot", description="Maintenance Copilot CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="Check that all four sidecar services are reachable.")
    p_ingest = sub.add_parser("ingest", help="Parse + chunk + index the sample manuals.")
    p_ingest.add_argument("--samples", default=None, help="Corpus dir (default: sample_manuals/).")
    sub.add_parser("index", help="Alias of ingest for the default corpus.")
    p_query = sub.add_parser("query", help="Retrieve top cited passages for a question.")
    p_query.add_argument("text")
    p_query.add_argument("--ata", default=None, help="Restrict to an ATA chapter.")
    p_query.add_argument("--k", type=int, default=5, help="Max hits (default 5).")
    p_query.add_argument(
        "--revision", default="current",
        help="'current' (default), a revision string, or 'none'.",
    )
    p_query.add_argument("--graph", action="store_true",
                         help="Attach related knowledge-graph entities (needs Neo4j).")
    p_query.add_argument("--synthesize", action="store_true",
                         help="Compose a cited answer (needs the synthesis LLM).")
    p_rec = sub.add_parser("recommend-refs", help="Rank AMM/MEL/CDL/TSM refs for a defect.")
    p_rec.add_argument("text")
    p_rec.add_argument("--k", type=int, default=5)
    p_val = sub.add_parser("validate", help="Validate cited refs against approved docs.")
    p_val.add_argument("payload", help="JSON string, or '-' to read stdin.")
    sub.add_parser("list", help="Show index stats.")
    sub.add_parser("reset", help="Delete the index collection.")
    p_graph = sub.add_parser("graph", help="Knowledge-graph build/query/verify.")
    graph_sub = p_graph.add_subparsers(dest="graph_command", required=True)
    g_build = graph_sub.add_parser("build", help="Extract + upsert the graph from the corpus.")
    g_build.add_argument("--samples", default=None)
    g_show = graph_sub.add_parser(
        "show",
        help="Show neighbors of an entity. hops>1 summarizes the terminal edge only.",
    )
    g_show.add_argument("key")
    g_show.add_argument("--hops", type=int, default=1)
    g_confirm = graph_sub.add_parser("confirm", help="Mark an edge engineer_confirmed.")
    g_confirm.add_argument("src")
    g_confirm.add_argument("edge_type")
    g_confirm.add_argument("dst")
    graph_sub.add_parser("stats", help="Graph node/edge counts.")
    graph_sub.add_parser("reset", help="Delete all graph data.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when ``None``).

    Returns:
        Exit code: ``0`` on success, ``1`` when a health probe fails,
        ``2`` for an unrecognized subcommand.
    """
    args = build_parser().parse_args(argv)
    if args.command == "health":
        result = check_health(_build_probes())
        print(json.dumps(result, indent=2))
        return 0 if all(v == "ok" for v in result.values()) else 1
    if args.command in ("ingest", "index"):
        return _cmd_ingest(args.samples if getattr(args, "samples", None) else _samples_dir())
    if args.command == "query":
        return _cmd_query(args.text, args.k, args.ata, args.revision,
                          args.graph, args.synthesize)
    if args.command == "recommend-refs":
        return _cmd_recommend_refs(args.text, args.k)
    if args.command == "validate":
        return _cmd_validate(args.payload)
    if args.command == "list":
        return _cmd_list()
    if args.command == "reset":
        return _cmd_reset()
    if args.command == "graph":
        if args.graph_command == "build":
            return _cmd_graph_build(
                args.samples if getattr(args, "samples", None) else _samples_dir()
            )
        if args.graph_command == "show":
            return _cmd_graph_show(args.key, args.hops)
        if args.graph_command == "confirm":
            return _cmd_graph_confirm(args.src, args.edge_type, args.dst)
        if args.graph_command == "stats":
            return _cmd_graph_stats()
        if args.graph_command == "reset":
            return _cmd_graph_reset()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
