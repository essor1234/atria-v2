"""Built-in tool schemas: knowledge tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Memory Tools =====
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": load_tool_description("memory_search"),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query — matches against content in all memory files",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": load_tool_description("memory_write"),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Topic name for the memory entry (used to generate filename)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the memory file",
                    },
                    "file": {
                        "type": "string",
                        "description": "Optional specific filename (e.g., 'patterns.md'). Auto-generated from topic if not specified.",
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["project", "user"],
                        "description": "Scope level: 'project' (.atria/memory/) or 'user' (~/.atria/memory/)",
                        "default": "project",
                    },
                },
                "required": ["topic", "content"],
            },
        },
    },
    # ===== Session Inspection Tools =====
    {
        "type": "function",
        "function": {
            "name": "list_sessions",
            "description": load_tool_description("list_sessions"),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of sessions to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_session_history",
            "description": load_tool_description("get_session_history"),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID of the session to read (from list_sessions)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return (default: 50)",
                        "default": 50,
                    },
                    "include_tool_calls": {
                        "type": "boolean",
                        "description": "Include tool call details in output (default: false)",
                        "default": False,
                    },
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_subagents",
            "description": load_tool_description("list_subagents"),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
