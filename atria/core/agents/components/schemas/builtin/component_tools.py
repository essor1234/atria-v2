"""Built-in tool schemas: module component rendering."""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "render_component",
            "description": load_tool_description("render-component"),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Module name (folder under the modules root).",
                    },
                    "block": {
                        "type": "string",
                        "description": (
                            "Block file basename (without .html) under the module's blocks/ dir."
                        ),
                    },
                    "props": {
                        "type": "object",
                        "description": "JSON-serializable data passed to the block. Max 256 KB.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title shown above the block.",
                    },
                    "height": {
                        "type": "string",
                        "description": "Block height: 'auto' or a pixel value. Defaults to 'auto'.",
                    },
                },
                "required": ["module", "block"],
            },
        },
    },
]
