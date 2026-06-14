# Design: domain_enrich Skill

**Date:** 2026-06-13
**Status:** Approved

## Overview

A new built-in skill that grounds the agent in domain knowledge before it starts any task. When a user asks the agent to do anything involving a specific domain (data analysis, game events, code generation for an unfamiliar API, etc.), the agent calls `domain_enrich(topic, context)` first. The tool searches the web, synthesizes a knowledge brief, writes a `DOMAIN_SKILL.md` artifact, and returns immediately. The agent then uses that artifact to inform its plan and response.

## Skill Structure

```
atria/skills/builtin/domain_enrich/
  SKILL.md        ← frontmatter: tools: tools.py; prose: when/how to invoke
  tools.py        ← registers domain_enrich ToolSpec with SkillToolContext
  engine.py       ← orchestrates query generation → search → synthesis → artifact write
  search.py       ← Serper/DuckDuckGo abstraction with fallback
```

No background jobs, no polling. Synchronous — completes in one call.

## Tool API

```python
domain_enrich(topic: str, context: str = "") -> dict
```

**Parameters:**
- `topic` — the domain to search (e.g. `"game event analytics"`, `"pandas DataFrame profiling"`)
- `context` — optional framing (e.g. `"for mobile RPG retention analysis"`)

**Returns:**
```json
{
  "artifact_path": "/path/to/DOMAIN_SKILL.md",
  "summary": "<first 300 chars of synthesized summary>",
  "sources": ["url1", "url2", ...]
}
```

## Search Backend (`search.py`)

Two backends, tried in order:

1. **Serper** — uses `SERPER_API_KEY` env var. POST to `https://google.serper.dev/search`. Returns structured Google results with titles, URLs, snippets.
2. **DuckDuckGo** — uses `duckduckgo-search` Python package (`DDGS().text()`). No API key required. Falls back to this when `SERPER_API_KEY` is absent or the Serper call fails.

`search.py` exposes a single function:
```python
def search(query: str, max_results: int = 5) -> list[dict]
# returns [{"title": ..., "url": ..., "snippet": ...}, ...]
```

If both backends fail, returns an empty list (engine proceeds with synthesis from topic+context alone).

## Engine Logic (`engine.py`)

1. **Generate queries** — LLM call (`ctx.llm_chat`) produces 3 search queries from topic + context. Example for `"game events"`: `["game analytics event taxonomy", "game event tracking best practices", "player behavior metrics game data"]`.
2. **Search** — run each query via `search.py`, collect up to 5 results per query, deduplicate by URL.
3. **Synthesize** — LLM call produces a structured brief from all collected snippets: key concepts, domain vocabulary, common metrics/patterns, gotchas.
4. **Write artifact** — write `DOMAIN_SKILL.md` to `ctx.working_dir`. Filename is fixed so multiple calls overwrite cleanly (latest enrichment wins).
5. **Emit artifact event** — call `ctx.on_artifact` if set, so the web UI surfaces the file.
6. **Return** — `artifact_path`, truncated `summary`, and `sources` list.

## Artifact Format (`DOMAIN_SKILL.md`)

```markdown
# Domain Knowledge: <topic>
> Context: <context>   ← omitted if context is empty
> Generated: <ISO timestamp>

## Summary
<LLM-synthesized brief: 3-5 paragraphs covering key concepts, vocabulary,
common metrics, typical patterns, and known gotchas in the domain>

## Raw Evidence

### <Result Title>
**URL:** <url>
<snippet text>

### <Result Title>
...
```

File is written to `{ctx.working_dir}/DOMAIN_SKILL.md`. Overwrites on repeat calls.

## SKILL.md Prose

The SKILL.md instructs the agent:

- Call `domain_enrich` before starting any task that involves a specific domain: data analysis, research, code generation for an unfamiliar library/API, answering domain-specific questions.
- Pass the user's topic as `topic` and any relevant framing as `context`.
- After the call, read the returned `summary` and the full `DOMAIN_SKILL.md` artifact to inform your plan.
- Skip if the domain is well-covered by the conversation history (i.e., `domain_enrich` was already called for this topic in the current session).

## System Prompt Instruction

A new file `atria/core/agents/prompts/templates/system/main/domain-enrichment.md` registered at priority 57 (between `action_safety` at 56 and the next section at 58), always included.

Content instructs the agent:
- Before starting any task involving a specific domain, call `domain_enrich(topic=..., context=...)` to ground yourself.
- Use the `DOMAIN_SKILL.md` artifact content to shape your analysis plan, terminology, and recommendations.
- One call per domain per session is sufficient — reuse the artifact if already generated.

## Dependencies

- `duckduckgo-search` — add to `pyproject.toml` as a runtime dependency.
- `requests` — already present (used by Serper call).
- No new optional deps; Serper key is purely env-based.

## Data Flow

```
User message
    │
    ▼
Agent reads SKILL.md instruction → calls domain_enrich(topic, context)
    │
    ▼
engine.py: generate queries (llm_chat)
    │
    ▼
search.py: Serper → fallback DuckDuckGo → collect results
    │
    ▼
engine.py: synthesize brief (llm_chat)
    │
    ▼
Write DOMAIN_SKILL.md → emit on_artifact → return {artifact_path, summary, sources}
    │
    ▼
Agent reads summary + artifact → proceeds with original task
```

## Error Handling

- If both search backends fail: engine proceeds with synthesis from topic+context alone (LLM uses its own knowledge). Tool does not raise — it degrades gracefully.
- If `llm_chat` is None: tool returns an error dict `{"error": "llm_chat not configured"}` without crashing.
- If `working_dir` is None: write artifact to system temp dir, log a warning.

## Testing

- Unit tests for `search.py`: mock HTTP/DDGS, assert fallback triggers on missing key and on Serper error.
- Unit tests for `engine.py`: mock `search`, mock `llm_chat`, assert artifact is written with correct structure.
- Unit test for `tools.py`: assert `register(ctx)` returns one `ToolSpec` named `domain_enrich`.
- Integration test: call `domain_enrich` with a real topic against mocked search, assert `DOMAIN_SKILL.md` exists and contains both Summary and Raw Evidence sections.
