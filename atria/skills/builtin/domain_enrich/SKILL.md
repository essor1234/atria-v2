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
