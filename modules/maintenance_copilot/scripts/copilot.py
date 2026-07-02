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
from typing import Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RoleConfig, load_config  # type: ignore[import-not-found]
from client import RoleClient  # type: ignore[import-not-found]
from corpus import load_corpus  # type: ignore[import-not-found]
from chunking import chunk_document  # type: ignore[import-not-found]
from index_store import IndexStore  # type: ignore[import-not-found]

# Output dimension of the deployed TEI embedding model (Qwen3-Embedding-0.6B).
# Must match the model configured for the index_embed role.
EMBED_DIM = 1024


def _samples_dir() -> str:
    return str(Path(__file__).resolve().parent.parent / "sample_manuals")


def _build_store(embed_fn: Optional[Callable] = None, qdrant: Optional[object] = None) -> IndexStore:
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


def check_health(probes: Dict[str, Callable[[], None]]) -> Dict[str, str]:
    """Run each probe; map name -> 'ok' or 'error: <message>'.

    Args:
        probes: Mapping of probe name to zero-argument callable. Each callable
            should raise on failure and return None on success.

    Returns:
        Dict mapping each probe name to ``"ok"`` or ``"error: <message>"``.
        Never raises — all exceptions are caught and recorded as errors.
    """
    out: Dict[str, str] = {}
    for name, probe in probes.items():
        try:
            probe()
            out[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - health must never raise
            out[name] = f"error: {exc}"
    return out


def _build_probes() -> Dict[str, Callable[[], None]]:
    """Build live probes against the configured sidecars."""
    cfg: Dict[str, RoleConfig] = load_config()
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


def _cmd_query(text: str, k: int, ata: Optional[str], revision: str) -> int:
    """Retrieve top cited passages for *text*.

    Args:
        text: Query string.
        k: Maximum number of hits.
        ata: Optional ATA chapter filter.
        revision: Revision filter string, or ``"none"`` to disable.

    Returns:
        ``0`` on success.
    """
    rev: Optional[str] = None if revision.lower() == "none" else revision
    store = _build_store()
    hits = store.query(text, k=k, ata_chapter=ata, revision=rev)
    print(json.dumps({"query": text, "hits": hits}, indent=2))
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
        Configured :class:`argparse.ArgumentParser` with the ``health``
        subcommand registered.
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
    sub.add_parser("list", help="Show index stats.")
    sub.add_parser("reset", help="Delete the index collection.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when ``None``).

    Returns:
        Exit code: ``0`` when every health probe is ``"ok"``, ``1`` when any
        probe fails, ``2`` for an unknown subcommand.
    """
    args = build_parser().parse_args(argv)
    if args.command == "health":
        result = check_health(_build_probes())
        print(json.dumps(result, indent=2))
        return 0 if all(v == "ok" for v in result.values()) else 1
    if args.command in ("ingest", "index"):
        return _cmd_ingest(args.samples if getattr(args, "samples", None) else _samples_dir())
    if args.command == "query":
        return _cmd_query(args.text, args.k, args.ata, args.revision)
    if args.command == "list":
        return _cmd_list()
    if args.command == "reset":
        return _cmd_reset()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
