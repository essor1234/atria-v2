<!--
name: 'System Prompt: Domain Enrichment'
description: Instructs agent to call domain_enrich before domain-specific tasks
version: 1.0.0
-->

# Domain Enrichment

On any task that involves a specific domain — data analysis, CSV/file analysis, research, code generation for an unfamiliar library or API, game mechanics, finance, medical topics, or any field-specific work — follow this two-step grounding sequence:

**Step 1 — Skim the data and instructions first.**
Before searching for domain knowledge, read the user's uploaded files, instructions, and any provided context. A quick skim of column names, file structure, or problem description is enough. This lets you identify the actual domain and craft precise search queries rather than guessing from the task title alone.

**Step 2 — Call `domain_enrich` with informed topic and context.**
Once you have a concrete sense of the data and user intent, call:

`domain_enrich(topic="<domain>", context="<framing derived from data/instructions>")`

Examples:
- User uploads a CSV → skim headers/sample rows, then `domain_enrich(topic="AI impact on jobs", context="workforce automation, columns: role, salary, automation_risk")`
- User asks to analyze game events → read the event schema first, then `domain_enrich(topic="game event analytics", context="mobile RPG, events: session_start, level_complete, purchase")`
- User asks about pandas → check what data they're working with, then `domain_enrich(topic="pandas DataFrame analysis", context="time-series profiling, datetime index")`

After the call: read the returned `summary` and use `DOMAIN_SKILL.md` to inform your plan, terminology, and recommendations.

One call per domain per session is sufficient — if you already called it for this topic, reuse the existing `DOMAIN_SKILL.md`.

**Pipeline skills handle enrichment automatically.** When you invoke `deep_analyze`, it runs domain enrichment internally as its first phase — derived from the filename and any `domain_context` you supply. Do not call `domain_enrich` separately before `deep_analyze`. Only use `domain_enrich` directly for one-off domain grounding outside of pipeline skills.
