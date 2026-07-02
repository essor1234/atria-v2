#!/usr/bin/env python
"""maintenance_copilot CLI.

Phase 1 ships the ``health`` subcommand: it verifies the four local sidecars
(TEI embeddings, Qdrant, Neo4j, local LLM) are reachable. Later phases add
``ingest``, ``index``, ``graph``, ``query``, ``validate``, and ``check``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RoleConfig, load_config  # type: ignore[import-not-found]
from client import RoleClient  # type: ignore[import-not-found]


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

        url = _service_url("MC_QDRANT_URL", "http://localhost:6333")
        QdrantClient(url=url).get_collections()

    def neo4j_probe() -> None:
        from neo4j import GraphDatabase  # local import: optional dep

        uri = _service_url("MC_NEO4J_URI", "bolt://localhost:7687")
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
    import os

    return os.environ.get(key, default)


def _service_url(key: str, default: str) -> str:
    return _env(key, default)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` with the ``health``
        subcommand registered.
    """
    parser = argparse.ArgumentParser(prog="copilot", description="Maintenance Copilot CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="Check that all four sidecar services are reachable.")
    return parser


def main(argv: Optional[list] = None) -> int:
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
