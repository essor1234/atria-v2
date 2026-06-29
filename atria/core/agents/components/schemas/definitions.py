"""Master list of built-in tool schemas used by Atria agents.

The complete schema definitions live in the :mod:`.builtin` subpackage, grouped
by domain (file, process, web, symbol, ...). They are reassembled here as
``_BUILTIN_TOOL_SCHEMAS`` for backwards-compatible imports.

Tool descriptions are loaded from markdown templates in
``atria/core/agents/prompts/templates/tools/``.
"""

from __future__ import annotations

from atria.core.agents.components.schemas.builtin import BUILTIN_TOOL_SCHEMAS
from atria.core.blackboard.note_rules import NOTE_RULES_BLOCK

_BUILTIN_TOOL_SCHEMAS = BUILTIN_TOOL_SCHEMAS

# ===== NOTE tool schema (shared blackboard) =====
# This schema is intentionally NOT part of _BUILTIN_TOOL_SCHEMAS.
# It is appended by ToolSchemaBuilder.build() only when
# config.blackboard.enabled is True, so that the tool is a true no-op
# (zero tokens, zero model calls) when the blackboard is disabled.
NOTE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "NOTE",
        "description": NOTE_RULES_BLOCK,
        "parameters": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "One to three typed note lines (or the literal `(none)`).",
                },
            },
            "required": ["body"],
        },
    },
}

__all__ = ["_BUILTIN_TOOL_SCHEMAS", "NOTE_SCHEMA"]
