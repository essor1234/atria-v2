"""Built-in tool schemas: artifact tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Markdown to PDF Tool (analyze plugin) =====
    {
        "type": "function",
        "function": {
            "name": "markdown_to_pdf",
            "description": load_tool_description("markdown-to-pdf"),
            "parameters": {
                "type": "object",
                "properties": {
                    "md_path": {
                        "type": "string",
                        "description": "Absolute path to the input markdown file.",
                    },
                    "pdf_path": {
                        "type": "string",
                        "description": "Absolute output path, must end in .pdf.",
                    },
                    "css_path": {
                        "type": "string",
                        "description": "Optional absolute path to a CSS file overriding the default report styles.",
                    },
                },
                "required": ["md_path", "pdf_path"],
            },
        },
    },
    # ===== Artifact Tools =====
    {
        "type": "function",
        "function": {
            "name": "list_artifact_images",
            "description": load_tool_description("list-artifact-images"),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["conversation", "project", "both"],
                        "description": "Scope to list artifacts from: 'conversation' for current conversation only, 'project' for entire project, 'both' for artifacts from both scopes",
                        "default": "conversation",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact_image",
            "description": load_tool_description("read-artifact-image"),
            "parameters": {
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "integer",
                        "description": "The ID of the artifact image to read",
                    },
                },
                "required": ["artifact_id"],
            },
        },
    },
]
