# domain_enrich Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `domain_enrich` built-in skill that searches the web (Serper → DuckDuckGo fallback), synthesizes a domain knowledge brief via LLM, writes `DOMAIN_SKILL.md`, and is invoked by the agent before any domain-specific task.

**Architecture:** New synchronous skill at `atria/skills/builtin/domain_enrich/` with four files (SKILL.md, tools.py, engine.py, search.py). A new system prompt section registered at priority 57 in `composition.py` instructs the agent to call it first. No background jobs — the tool blocks and returns in one call.

**Tech Stack:** Python, `httpx` (Serper), `duckduckgo-search` (already in pyproject.toml), `atria.core.skill_tools.SkillToolContext`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `atria/skills/builtin/domain_enrich/SKILL.md` | Skill descriptor + agent instructions |
| Create | `atria/skills/builtin/domain_enrich/tools.py` | `register(ctx)` → `ToolSpec` for `domain_enrich` |
| Create | `atria/skills/builtin/domain_enrich/engine.py` | Orchestrate: queries → search → synthesis → artifact |
| Create | `atria/skills/builtin/domain_enrich/search.py` | Serper+DuckDuckGo search abstraction |
| Create | `atria/core/agents/prompts/templates/system/main/domain-enrichment.md` | System prompt section |
| Modify | `atria/core/agents/prompts/composition.py:192` | Register domain-enrichment at priority 57 |
| Create | `tests/test_domain_enrich_search.py` | Unit tests for search.py |
| Create | `tests/test_domain_enrich_engine.py` | Unit tests for engine.py |
| Create | `tests/test_domain_enrich_tools.py` | Unit tests for tools.py registration |

---

## Task 1: search.py — Serper + DuckDuckGo abstraction

**Files:**
- Create: `atria/skills/builtin/domain_enrich/search.py`
- Test: `tests/test_domain_enrich_search.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_domain_enrich_search.py`:

```python
"""Tests for domain_enrich search backend."""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch


def _import_search():
    import atria.skills.builtin.domain_enrich.search as m
    importlib.reload(m)
    return m


class TestSerperSearch:
    def test_returns_empty_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        m = _import_search()
        assert m._serper_search("python", 5) == []

    def test_returns_results_when_key_set(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake-key")
        fake_response = {
            "organic": [
                {"title": "Python Docs", "link": "https://python.org", "snippet": "Official docs"},
            ]
        }
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status = MagicMock()
            mock_cm = MagicMock()
            mock_cm.__aenter__ = MagicMock(return_value=mock_resp)
            mock_cm.__aexit__ = MagicMock(return_value=False)
            mock_client = MagicMock()
            mock_client.post.return_value = mock_cm
            mock_client_cls.return_value.__aenter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = MagicMock(return_value=False)

            m = _import_search()
            results = m._serper_search("python", 5)

        assert len(results) == 1
        assert results[0]["title"] == "Python Docs"
        assert results[0]["url"] == "https://python.org"
        assert results[0]["snippet"] == "Official docs"

    def test_returns_empty_on_serper_error(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake-key")
        with patch("httpx.AsyncClient", side_effect=Exception("network error")):
            m = _import_search()
            assert m._serper_search("python", 5) == []


class TestDdgSearch:
    def test_returns_results_from_ddgs(self):
        fake_results = [
            {"title": "DDG Result", "href": "https://example.com", "body": "A snippet"},
        ]
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = fake_results

        with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
            m = _import_search()
            results = m._ddg_search("python", 5)

        assert results == [{"title": "DDG Result", "url": "https://example.com", "snippet": "A snippet"}]

    def test_returns_empty_on_ddg_error(self):
        with patch("duckduckgo_search.DDGS", side_effect=Exception("rate limited")):
            m = _import_search()
            assert m._ddg_search("python", 5) == []


class TestSearchFallback:
    def test_uses_serper_when_key_present(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "key")
        m = _import_search()
        serper_results = [{"title": "S", "url": "https://s.com", "snippet": "s"}]
        with patch.object(m, "_serper_search", return_value=serper_results) as mock_s, \
             patch.object(m, "_ddg_search", return_value=[]) as mock_d:
            results = m.search("python", 5)
        mock_s.assert_called_once_with("python", 5)
        mock_d.assert_not_called()
        assert results == serper_results

    def test_falls_back_to_ddg_when_serper_empty(self, monkeypatch):
        monkeypatch.delenv("SERPER_API_KEY", raising=False)
        m = _import_search()
        ddg_results = [{"title": "D", "url": "https://d.com", "snippet": "d"}]
        with patch.object(m, "_serper_search", return_value=[]) as mock_s, \
             patch.object(m, "_ddg_search", return_value=ddg_results) as mock_d:
            results = m.search("python", 5)
        mock_s.assert_called_once()
        mock_d.assert_called_once_with("python", 5)
        assert results == ddg_results
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_domain_enrich_search.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError` or `ImportError` — the module doesn't exist yet.

- [ ] **Step 3: Create `atria/skills/builtin/domain_enrich/search.py`**

```python
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
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()
    except Exception:
        logger.debug("Serper search failed for %r", query)
        return []


def _ddg_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """DuckDuckGo search fallback. Returns [] on error."""
    try:
        from duckduckgo_search import DDGS

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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_domain_enrich_search.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/skills/builtin/domain_enrich/search.py tests/test_domain_enrich_search.py
git commit -m "feat(domain_enrich): add search.py — Serper + DDG fallback"
```

---

## Task 2: engine.py — query generation, search orchestration, synthesis, artifact write

**Files:**
- Create: `atria/skills/builtin/domain_enrich/engine.py`
- Test: `tests/test_domain_enrich_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_domain_enrich_engine.py`:

```python
"""Tests for domain_enrich engine."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atria.skills.builtin.domain_enrich.engine import (
    _generate_queries,
    _synthesize,
    _write_artifact,
    run_enrich,
)


class TestGenerateQueries:
    def test_returns_three_queries_from_llm(self):
        chat_fn = MagicMock(return_value='["game events", "game analytics KPIs", "player retention"]')
        result = _generate_queries("game events", "", chat_fn)
        assert result == ["game events", "game analytics KPIs", "player retention"]

    def test_falls_back_to_defaults_on_invalid_json(self):
        chat_fn = MagicMock(return_value="I cannot generate queries")
        result = _generate_queries("game events", "", chat_fn)
        assert result == ["game events", "game events metrics", "game events best practices"]

    def test_includes_context_in_llm_prompt(self):
        chat_fn = MagicMock(return_value='["q1", "q2", "q3"]')
        _generate_queries("game events", "for mobile RPG", chat_fn)
        call_args = chat_fn.call_args
        user_prompt = call_args[0][1]
        assert "for mobile RPG" in user_prompt

    def test_falls_back_on_llm_exception(self):
        chat_fn = MagicMock(side_effect=Exception("LLM error"))
        result = _generate_queries("topic", "", chat_fn)
        assert len(result) == 3
        assert result[0] == "topic"


class TestSynthesize:
    def test_returns_llm_output(self):
        chat_fn = MagicMock(return_value="Game events are discrete player actions...")
        result = _synthesize("game events", ["evidence 1", "evidence 2"], chat_fn)
        assert result == "Game events are discrete player actions..."

    def test_handles_empty_evidence(self):
        chat_fn = MagicMock(return_value="Knowledge from training.")
        result = _synthesize("game events", [], chat_fn)
        assert "Knowledge from training." == result
        user_prompt = chat_fn.call_args[0][1]
        assert "No search results" in user_prompt

    def test_returns_error_string_on_llm_failure(self):
        chat_fn = MagicMock(side_effect=Exception("timeout"))
        result = _synthesize("topic", [], chat_fn)
        assert "unavailable" in result.lower()


class TestWriteArtifact:
    def test_creates_domain_skill_md(self, tmp_path):
        path = _write_artifact(
            topic="game events",
            context="for RPG",
            summary="Game events are actions...",
            results=[{"title": "Example", "url": "https://ex.com", "snippet": "A snippet"}],
            working_dir=str(tmp_path),
        )
        assert Path(path).exists()
        assert Path(path).name == "DOMAIN_SKILL.md"

    def test_artifact_contains_summary_and_evidence(self, tmp_path):
        path = _write_artifact(
            topic="game events",
            context="",
            summary="Summary text here",
            results=[{"title": "T", "url": "https://t.com", "snippet": "snippet text"}],
            working_dir=str(tmp_path),
        )
        content = Path(path).read_text()
        assert "## Summary" in content
        assert "Summary text here" in content
        assert "## Raw Evidence" in content
        assert "snippet text" in content
        assert "https://t.com" in content

    def test_writes_to_tempdir_when_working_dir_none(self):
        path = _write_artifact("topic", "", "summary", [], working_dir=None)
        assert Path(path).exists()
        Path(path).unlink(missing_ok=True)

    def test_overwrites_on_second_call(self, tmp_path):
        _write_artifact("t", "", "first", [], str(tmp_path))
        path = _write_artifact("t", "", "second", [], str(tmp_path))
        assert "second" in Path(path).read_text()
        assert "first" not in Path(path).read_text()


class TestRunEnrich:
    def test_returns_error_when_no_llm_chat(self, tmp_path):
        result = run_enrich("topic", "", chat_fn=None, working_dir=str(tmp_path), on_artifact=None)
        assert "error" in result
        assert result["artifact_path"] is None

    def test_full_pipeline_writes_artifact(self, tmp_path):
        chat_fn = MagicMock(
            side_effect=[
                '["game kpis", "game analytics", "game metrics"]',
                "Game events are discrete player actions tracked for analytics.",
            ]
        )
        search_results = [{"title": "T", "url": "https://t.com", "snippet": "snippet"}]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=search_results):
            result = run_enrich("game events", "for RPG", chat_fn, str(tmp_path), None)

        assert result["artifact_path"] is not None
        assert Path(result["artifact_path"]).exists()
        assert len(result["sources"]) > 0
        assert len(result["summary"]) > 0

    def test_deduplicates_search_results_by_url(self, tmp_path):
        chat_fn = MagicMock(
            side_effect=[
                '["q1", "q2", "q3"]',
                "synthesis",
            ]
        )
        duplicate_results = [{"title": "T", "url": "https://same.com", "snippet": "s"}]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=duplicate_results):
            result = run_enrich("topic", "", chat_fn, str(tmp_path), None)

        assert result["sources"].count("https://same.com") == 1

    def test_calls_on_artifact_callback(self, tmp_path):
        chat_fn = MagicMock(side_effect=['["q1", "q2", "q3"]', "synthesis"])
        on_artifact = MagicMock()

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            run_enrich("topic", "", chat_fn, str(tmp_path), on_artifact)

        on_artifact.assert_called_once()
        call_kwargs = on_artifact.call_args[0][0]
        assert call_kwargs["type"] == "domain_skill"
        assert "topic" in call_kwargs

    def test_proceeds_without_search_results(self, tmp_path):
        chat_fn = MagicMock(side_effect=['["q1", "q2", "q3"]', "Knowledge from training only."])

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            result = run_enrich("obscure topic", "", chat_fn, str(tmp_path), None)

        assert result["artifact_path"] is not None
        assert "Knowledge from training only." in result["summary"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_domain_enrich_engine.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError` — engine.py doesn't exist yet.

- [ ] **Step 3: Create `atria/skills/builtin/domain_enrich/engine.py`**

```python
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
                return [str(q) for q in parsed[:3] if q]
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
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_domain_enrich_engine.py -v
```
Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/skills/builtin/domain_enrich/engine.py tests/test_domain_enrich_engine.py
git commit -m "feat(domain_enrich): add engine.py — query gen, search, synthesis, artifact write"
```

---

## Task 3: SKILL.md + tools.py — skill descriptor and tool registration

**Files:**
- Create: `atria/skills/builtin/domain_enrich/SKILL.md`
- Create: `atria/skills/builtin/domain_enrich/tools.py`
- Test: `tests/test_domain_enrich_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_domain_enrich_tools.py`:

```python
"""Tests for domain_enrich tools registration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from atria.core.skill_tools import SkillToolContext, ToolSpec


class TestRegister:
    def test_returns_one_toolspec(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        specs = register(ctx)
        assert len(specs) == 1
        assert isinstance(specs[0], ToolSpec)

    def test_toolspec_named_domain_enrich(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert spec.name == "domain_enrich"

    def test_toolspec_requires_topic_parameter(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert "topic" in spec.parameters["properties"]
        assert "topic" in spec.parameters["required"]

    def test_toolspec_context_parameter_optional(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert "context" in spec.parameters["properties"]
        assert "context" not in spec.parameters.get("required", [])

    def test_handler_delegates_to_run_enrich(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext(
            llm_chat=MagicMock(side_effect=['["q1","q2","q3"]', "synthesis"]),
            working_dir="/tmp",
        )
        spec = register(ctx)[0]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            result = spec.handler(topic="game events")

        assert "artifact_path" in result
        assert "summary" in result
        assert "sources" in result

    def test_handler_passes_context_to_run_enrich(self):
        from atria.skills.builtin.domain_enrich import engine
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]

        with patch.object(engine, "run_enrich", return_value={}) as mock_run:
            spec.handler(topic="topic", context="some context")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["context"] == "some context"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_domain_enrich_tools.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` — tools.py doesn't exist yet.

- [ ] **Step 3: Create `atria/skills/builtin/domain_enrich/SKILL.md`**

```markdown
---
name: domain_enrich
description: Grounding skill — web search + LLM synthesis into DOMAIN_SKILL.md before domain-specific tasks.
tools: tools.py
---

Before starting any task that involves a specific domain — data analysis, research,
code generation for an unfamiliar library or API, game mechanics, finance, medicine,
or any field-specific work — call `domain_enrich(topic=..., context=...)` to ground
yourself in the relevant domain knowledge.

Pass the domain as `topic` (e.g. `"game event analytics"`, `"pandas profiling"`,
`"options trading Greeks"`). Use `context` for any framing that narrows the search
(e.g. `"for mobile RPG retention analysis"`).

After the call:
1. Read the `summary` in the return value for a quick brief.
2. The full `DOMAIN_SKILL.md` artifact is written to the working directory — reference
   it when planning your analysis, choosing terminology, and forming recommendations.

One call per domain per session is sufficient. If you have already called
`domain_enrich` for this topic in the current conversation, reuse the existing
`DOMAIN_SKILL.md` rather than calling again.
```

- [ ] **Step 4: Create `atria/skills/builtin/domain_enrich/tools.py`**

```python
"""Skill entry point: register() returns ToolSpec for domain_enrich."""

from __future__ import annotations

from atria.core.skill_tools import SkillToolContext, ToolSpec

from .engine import run_enrich

_PARAMS = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": (
                "The domain to search and summarize "
                "(e.g. 'game event analytics', 'pandas DataFrame profiling')."
            ),
        },
        "context": {
            "type": "string",
            "description": (
                "Optional framing for the search "
                "(e.g. 'for mobile RPG retention analysis')."
            ),
            "default": "",
        },
    },
    "required": ["topic"],
}


def register(ctx: SkillToolContext) -> list[ToolSpec]:
    def _handler(topic: str, context: str = "") -> dict:
        return run_enrich(
            topic=topic.strip(),
            context=context.strip(),
            chat_fn=ctx.llm_chat,
            working_dir=ctx.working_dir,
            on_artifact=ctx.on_artifact,
        )

    return [
        ToolSpec(
            name="domain_enrich",
            description=(
                "Search the web and synthesize domain knowledge into DOMAIN_SKILL.md. "
                "Call this before starting any domain-specific task."
            ),
            parameters=_PARAMS,
            handler=_handler,
        )
    ]
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_domain_enrich_tools.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add atria/skills/builtin/domain_enrich/SKILL.md atria/skills/builtin/domain_enrich/tools.py tests/test_domain_enrich_tools.py
git commit -m "feat(domain_enrich): add SKILL.md and tools.py — tool registration"
```

---

## Task 4: System prompt section + composition registration

**Files:**
- Create: `atria/core/agents/prompts/templates/system/main/domain-enrichment.md`
- Modify: `atria/core/agents/prompts/composition.py` (line 192, after `action_safety`)

- [ ] **Step 1: Create `atria/core/agents/prompts/templates/system/main/domain-enrichment.md`**

```markdown
<!--
name: 'System Prompt: Domain Enrichment'
description: Instructs agent to call domain_enrich before domain-specific tasks
version: 1.0.0
-->

# Domain Enrichment

Before starting any task involving a specific domain — data analysis, research, code
generation for an unfamiliar library or API, or answering domain-specific questions —
call `domain_enrich(topic=..., context=...)` to ground yourself in the relevant domain
knowledge first.

Use the returned `summary` and the full `DOMAIN_SKILL.md` artifact to shape your
analysis plan, terminology, and recommendations.

One call per domain per session is sufficient. If `DOMAIN_SKILL.md` already exists
for this topic in the current conversation, read it instead of calling again.
```

- [ ] **Step 2: Register the section in `composition.py`**

In `atria/core/agents/prompts/composition.py`, find line 192:
```python
    composer.register_section("action_safety", "system/main/main-action-safety.md", priority=56)
```

Add immediately after it:
```python
    composer.register_section(
        "domain_enrichment",
        "system/main/domain-enrichment.md",
        priority=57,
    )
```

- [ ] **Step 3: Verify the section loads in the composed prompt**

```bash
uv run python -c "
from atria.core.agents.prompts.composition import build_main_composer
composer = build_main_composer()
prompt = composer.compose({})
assert 'Domain Enrichment' in prompt, 'section not found in prompt'
print('OK — domain_enrichment section present in composed prompt')
"
```
Expected output: `OK — domain_enrichment section present in composed prompt`

- [ ] **Step 4: Commit**

```bash
git add atria/core/agents/prompts/templates/system/main/domain-enrichment.md atria/core/agents/prompts/composition.py
git commit -m "feat(domain_enrich): add system prompt section at priority 57"
```

---

## Task 5: Integration test — full pipeline end-to-end

**Files:**
- Test: `tests/test_domain_enrich_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_domain_enrich_integration.py`:

```python
"""Integration test: domain_enrich full pipeline with mocked search + LLM."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from atria.core.skill_tools import SkillToolContext
from atria.skills.builtin.domain_enrich.tools import register


def test_full_pipeline_produces_valid_artifact(tmp_path):
    """domain_enrich tool writes DOMAIN_SKILL.md with Summary and Raw Evidence."""
    chat_fn = MagicMock(
        side_effect=[
            '["game event taxonomy", "game analytics KPIs", "player behavior metrics"]',
            "Game events are discrete player actions (session starts, level completions, purchases) tracked as timestamped records for retention and monetization analysis.",
        ]
    )
    search_results = [
        {"title": "Game Analytics 101", "url": "https://gameanalytics.com/blog", "snippet": "Event tracking is the foundation of game analytics."},
        {"title": "KPI Guide", "url": "https://example.com/kpis", "snippet": "DAU, MAU, ARPU are core game metrics."},
    ]

    ctx = SkillToolContext(
        llm_chat=chat_fn,
        working_dir=str(tmp_path),
        on_artifact=None,
    )
    spec = register(ctx)[0]

    with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=search_results):
        result = spec.handler(topic="game event analytics", context="for mobile RPG")

    # Return value is well-formed
    assert result.get("artifact_path") is not None
    assert len(result.get("sources", [])) > 0
    assert len(result.get("summary", "")) > 0

    # Artifact file exists and has correct structure
    artifact = Path(result["artifact_path"])
    assert artifact.exists()
    assert artifact.name == "DOMAIN_SKILL.md"

    content = artifact.read_text()
    assert "# Domain Knowledge: game event analytics" in content
    assert "## Summary" in content
    assert "## Raw Evidence" in content
    assert "https://gameanalytics.com/blog" in content
    assert "Game Analytics 101" in content


def test_tool_registered_and_discoverable():
    """SkillToolLoader discovers domain_enrich via SKILL.md."""
    from pathlib import Path
    from atria.core.skill_tools import SkillToolContext, SkillToolLoader

    builtin_dir = Path(__file__).parent.parent / "atria" / "skills" / "builtin"
    loader = SkillToolLoader([builtin_dir])
    ctx = SkillToolContext()
    specs = loader.discover_and_register(ctx)

    names = [s.name for s in specs]
    assert "domain_enrich" in names, f"domain_enrich not found in: {names}"
```

- [ ] **Step 2: Run the integration tests**

```bash
uv run pytest tests/test_domain_enrich_integration.py -v
```
Expected: both tests PASS.

- [ ] **Step 3: Run the full test suite to check for regressions**

```bash
uv run pytest tests/ -x -q 2>&1 | tail -20
```
Expected: no new failures.

- [ ] **Step 4: Commit**

```bash
git add tests/test_domain_enrich_integration.py
git commit -m "test(domain_enrich): add integration tests"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `search.py` — Serper+DDG fallback (Tasks 1)
- ✅ `engine.py` — query gen, search, synthesis, artifact write (Task 2)
- ✅ `tools.py` + `SKILL.md` — tool registration (Task 3)
- ✅ System prompt section at priority 57 (Task 4)
- ✅ `DOMAIN_SKILL.md` format: summary + raw evidence (Tasks 2, 5)
- ✅ `duckduckgo-search` already in `pyproject.toml` — no change needed
- ✅ `on_artifact` callback called (Task 2 tests)
- ✅ Graceful degradation when search/LLM fails (Tasks 1, 2 tests)
- ✅ Integration: full pipeline + SkillToolLoader discovery (Task 5)

**Placeholder scan:** No TBDs or TODOs present.

**Type consistency:** `run_enrich` signature used identically in engine.py, tools.py, and tests. `ToolSpec`, `SkillToolContext` imported from same module across all files.
