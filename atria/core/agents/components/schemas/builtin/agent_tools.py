"""Built-in tool schemas: agent tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Agents Listing Tool =====
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": load_tool_description("list_agents"),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # ===== Apply Patch Tool =====
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": load_tool_description("apply_patch"),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "Unified diff patch content",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "Validate patch without applying (default: false)",
                        "default": False,
                    },
                },
                "required": ["patch"],
            },
        },
    },
    # ===== Task Completion Tool =====
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": load_tool_description("task_complete"),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "Summary of what was accomplished. Include key details: "
                            "file paths created/modified, URLs, ports, commands to run, "
                            "or test results. "
                            "Be specific enough that the user can act on this summary alone."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "enum": ["success", "partial", "failed"],
                        "description": "Completion status: 'success' if fully completed, 'partial' if some parts done, 'failed' if couldn't complete",
                        "default": "success",
                    },
                },
                "required": ["summary", "status"],
            },
        },
    },
    # MCP Tool Discovery (Token-Efficient)
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": load_tool_description("search_tools"),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - matches tool names and descriptions. Use '*' or empty string to list all tools.",
                    },
                    "detail_level": {
                        "type": "string",
                        "enum": ["names", "brief", "full"],
                        "description": "Level of detail: 'names' (tool names only), 'brief' (names + one-line descriptions), 'full' (complete schemas including parameters)",
                        "default": "brief",
                    },
                    "server": {
                        "type": "string",
                        "description": "Optional: filter to specific MCP server name",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # Skills System Tool
    {
        "type": "function",
        "function": {
            "name": "invoke_skill",
            "description": load_tool_description("invoke_skill"),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to invoke. Can include namespace prefix (e.g., 'git:commit'). Leave empty to list available skills.",
                    },
                },
                "required": [],
            },
        },
    },
    # ===== Task Output Tool =====
    {
        "type": "function",
        "function": {
            "name": "get_subagent_output",
            "description": load_tool_description("get_subagent_output"),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The task_id returned when a background subagent was spawned (NOT the tool_call_id). "
                        "Only subagents with run_in_background=true return a task_id.",
                    },
                    "block": {
                        "type": "boolean",
                        "description": "Whether to wait for completion. Set to false for non-blocking status check.",
                        "default": True,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum wait time in milliseconds (max 600000)",
                        "default": 30000,
                        "maximum": 600000,
                    },
                },
                "required": ["task_id"],
            },
        },
    },
]
