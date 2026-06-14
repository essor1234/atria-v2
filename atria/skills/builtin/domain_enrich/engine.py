"""Domain enrichment engine: queries → search → synthesis → DOMAIN_SKILL.md."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import search as search_mod

logger = logging.getLogger(__name__)

_QUERY_SYSTEM = (
    "You generate web search queries to build domain knowledge. "
    "Return a JSON array of exactly 3 short search query strings. "
    "No objects — just strings. Queries must cover: core concepts/terminology, "
    "common metrics/patterns, and best practices."
)

_SYNTHESIS_SYSTEM = (
    "You synthesize web search results into a structured domain knowledge brief. "
    "Write 3-5 paragraphs covering: key concepts, domain vocabulary, common metrics, "
    "typical patterns, and known gotchas. Be precise and concrete. No filler."
)


def _generate_queries(
    topic: str, context: str, chat_fn: Callable[[str, str], str]
) -> list[str]:
    user = f"Topic: {topic}"
    if context:
        user += f"\nContext: {context}"
    try:
        raw = chat_fn(_QUERY_SYSTEM, user)
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            if isinstance(parsed, list):
                queries = [
                    str(q).strip()
                    for q in parsed[:3]
                    if isinstance(q, str) and str(q).strip()
                ]
                if queries:
                    defaults = [
                        topic,
                        f"{topic} metrics",
                        f"{topic} best practices",
                    ]
                    while len(queries) < 3:
                        queries.append(defaults[len(queries)])
                    return queries
    except Exception:
        logger.debug("Query generation failed, using defaults for %r", topic)
    return [topic, f"{topic} metrics", f"{topic} best practices"]


def _synthesize(
    topic: str, evidence: list[str], chat_fn: Callable[[str, str], str]
) -> str:
    if evidence:
        user = f"Topic: {topic}\n\nSearch evidence:\n" + "\n\n".join(evidence[:15])
    else:
        user = f"Topic: {topic}\n\n(No search results available — use your training knowledge.)"
    try:
        return chat_fn(_SYNTHESIS_SYSTEM, user)
    except Exception as exc:
        logger.warning("Synthesis LLM call failed: %s", exc)
        return f"Domain knowledge synthesis unavailable: {exc}"


def _write_artifact(
    topic: str,
    context: str,
    summary: str,
    results: list[dict[str, Any]],
    working_dir: str | None,
) -> str:
    lines = [f"# Domain Knowledge: {topic}"]
    if context:
        lines.append(f"> Context: {context}")
    lines.append(f"> Generated: {datetime.now(timezone.utc).isoformat()}")
    lines += ["", "## Summary", "", summary, "", "## Raw Evidence"]

    for r in results:
        title = r.get("title") or "Result"
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        lines.append(f"\n### {title}")
        if url:
            lines.append(f"**URL:** {url}")
        if snippet:
            lines.append(snippet)

    content = "\n".join(lines)
    out_dir = Path(working_dir) if working_dir else Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "DOMAIN_SKILL.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def run_enrich(
    topic: str,
    context: str,
    chat_fn: Callable[[str, str], str] | None,
    working_dir: str | None,
    on_artifact: Callable[[dict[str, Any]], None] | None,
) -> dict[str, Any]:
    if not chat_fn:
        return {
            "error": "llm_chat not configured",
            "artifact_path": None,
            "summary": "",
            "sources": [],
        }

    queries = _generate_queries(topic, context, chat_fn)

    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        for r in search_mod.search(q, max_results=5):
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    evidence = [
        f"**{r.get('title', '')}** ({r.get('url', '')})\n{r.get('snippet', '')}"
        for r in all_results
        if r.get("snippet")
    ]

    summary = _synthesize(topic, evidence, chat_fn)
    artifact_path = _write_artifact(topic, context, summary, all_results, working_dir)

    if on_artifact:
        try:
            on_artifact({"type": "domain_skill", "path": artifact_path, "topic": topic})
        except Exception as exc:
            logger.debug("on_artifact callback failed: %s", exc)

    return {
        "artifact_path": artifact_path,
        "summary": summary[:300],
        "sources": [r.get("url", "") for r in all_results if r.get("url")],
        "error": None,
    }
