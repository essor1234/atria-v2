"""Built-in tool schemas: knowledge tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Git Tool =====
    {
        "type": "function",
        "function": {
            "name": "git",
            "description": load_tool_description("git"),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "status",
                            "diff",
                            "log",
                            "branch",
                            "checkout",
                            "commit",
                            "push",
                            "pull",
                            "stash",
                            "merge",
                            "create_pr",
                        ],
                        "description": "Git action to perform",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name (for checkout, merge, push, branch)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message (for commit) or stash message (for stash push)",
                    },
                    "file": {
                        "type": "string",
                        "description": "File path (for diff)",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged changes only (for diff)",
                        "default": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of entries to show (for log)",
                        "default": 10,
                    },
                    "remote": {
                        "type": "string",
                        "description": "Remote name (for push/pull)",
                        "default": "origin",
                    },
                    "force": {
                        "type": "boolean",
                        "description": "Force push (uses --force-with-lease). Blocked for protected branches.",
                        "default": False,
                    },
                    "create": {
                        "type": "boolean",
                        "description": "Create new branch (for checkout -b)",
                        "default": False,
                    },
                    "title": {
                        "type": "string",
                        "description": "PR title (for create_pr)",
                    },
                    "body": {
                        "type": "string",
                        "description": "PR body/description (for create_pr)",
                    },
                    "base": {
                        "type": "string",
                        "description": "Base branch for PR (for create_pr)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Branch name (for branch create/delete)",
                    },
                    "delete": {
                        "type": "boolean",
                        "description": "Delete the branch (for branch)",
                        "default": False,
                    },
                },
                "required": ["action"],
            },
        },
    },
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
