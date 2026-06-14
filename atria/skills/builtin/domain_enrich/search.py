"""Web search backend: Serper (primary) → DuckDuckGo (fallback)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


def _serper_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Call Serper API synchronously. Returns [] if no key or on error."""
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        return []

    async def _call() -> list[dict[str, Any]]:
        import httpx

        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = json.dumps({"q": query, "num": max_results})
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(_SERPER_URL, headers=headers, content=payload)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in (data.get("organic") or [])[:max_results]:
            url = (item.get("link") or "").strip()
            if url:
                results.append(
                    {
                        "title": (item.get("title") or "").strip(),
                        "url": url,
                        "snippet": (item.get("snippet") or "").strip(),
                    }
                )
        return results

    try:
        return asyncio.run(_call())
    except Exception:
        logger.debug("Serper search failed for %r", query)
        return []


def _ddg_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """DuckDuckGo search fallback. Returns [] on error."""
    try:
        from ddgs import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        return results
    except Exception:
        logger.debug("DuckDuckGo search failed for %r", query)
        return []


def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search the web. Tries Serper first, falls back to DuckDuckGo."""
    results = _serper_search(query, max_results)
    if not results:
        results = _ddg_search(query, max_results)
    return results
