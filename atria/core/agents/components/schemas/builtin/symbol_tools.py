"""Built-in tool schemas: symbol tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Symbol Tools (LSP-based) =====
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": load_tool_description("find_symbol"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name path pattern to search for. Examples: 'MyClass' (class), 'MyClass.method' (method in class), 'my_func' (function), 'My*' (wildcard)",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional file path to limit search scope. If not provided, searches the workspace.",
                    },
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_referencing_symbols",
            "description": load_tool_description("find_referencing_symbols"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to find references for",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file where the symbol is defined (required to locate the symbol)",
                    },
                    "include_declaration": {
                        "type": "boolean",
                        "description": "Whether to include the declaration itself in results",
                        "default": True,
                    },
                },
                "required": ["symbol_name", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_before_symbol",
            "description": load_tool_description("insert_before_symbol"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to insert before",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "content": {
                        "type": "string",
                        "description": "Code content to insert",
                    },
                },
                "required": ["symbol_name", "file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_after_symbol",
            "description": load_tool_description("insert_after_symbol"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol to insert after",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "content": {
                        "type": "string",
                        "description": "Code content to insert",
                    },
                },
                "required": ["symbol_name", "file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_symbol_body",
            "description": load_tool_description("replace_symbol_body"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Name of the symbol whose body to replace",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file containing the symbol",
                    },
                    "new_body": {
                        "type": "string",
                        "description": "New body content for the symbol",
                    },
                    "preserve_signature": {
                        "type": "boolean",
                        "description": "Whether to keep the function/method signature (default: true)",
                        "default": True,
                    },
                },
                "required": ["symbol_name", "file_path", "new_body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_symbol",
            "description": load_tool_description("rename_symbol"),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Current name of the symbol to rename",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to file where symbol is defined",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the symbol",
                    },
                },
                "required": ["symbol_name", "file_path", "new_name"],
            },
        },
    },
]
