"""Skill entry point: register() returns ToolSpec for domain_enrich."""

from __future__ import annotations

from atria.core.skill_tools import SkillToolContext, ToolSpec

from . import engine

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
        return engine.run_enrich(
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
