"""Built-in tool schemas: file tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": load_tool_description("write_file"),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path where the file should be created (e.g., 'app.py', 'src/main.js')",
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete content to write to the file",
                    },
                    "create_dirs": {
                        "type": "boolean",
                        "description": "Whether to create parent directories if they don't exist",
                        "default": True,
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": load_tool_description("edit_file"),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit",
                    },
                    "old_content": {
                        "type": "string",
                        "description": "The exact text to find and replace in the file",
                    },
                    "new_content": {
                        "type": "string",
                        "description": "The new text to replace the old content with",
                    },
                    "match_all": {
                        "type": "boolean",
                        "description": "Whether to replace all occurrences (true) or just the first one (false)",
                        "default": False,
                    },
                },
                "required": ["file_path", "old_content", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": load_tool_description("read_file"),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "1-based line number to start reading from. Defaults to 1.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum number of lines to return. Defaults to 2000.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": load_tool_description("list_files"),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to list",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g., '*.py', '**/*.js')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 100,
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth to traverse when listing without a glob pattern",
                        "default": 2,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": load_tool_description("search"),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern. For text mode: regex pattern. For AST mode: structural pattern with $VAR wildcards (e.g., '$A && $A()', 'console.log($MSG)')",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search. Be specific to avoid timeouts.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["text", "ast"],
                        "description": "Search type: 'text' for regex/string matching (default), 'ast' for structural code patterns",
                        "default": "text",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language hint for AST mode: python, typescript, javascript, go, rust, java, etc. Auto-detected if not specified.",
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Case insensitive search (default false)",
                        "default": False,
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Number of context lines before and after each match",
                        "default": 0,
                    },
                    "include_glob": {
                        "type": "string",
                        "description": "Glob pattern to filter which files to search (e.g., '*.py', '*.{ts,tsx}')",
                    },
                    "file_type": {
                        "type": "string",
                        "description": "File type filter (e.g., 'py', 'js', 'rust', 'go', 'java'). More efficient than include_glob.",
                    },
                    "multiline": {
                        "type": "boolean",
                        "description": "Enable multiline matching where . matches newlines and patterns can span lines",
                        "default": False,
                    },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files_with_matches", "count"],
                        "description": "Output format: 'content' shows matching lines (default), 'files_with_matches' shows only file paths, 'count' shows match counts per file",
                        "default": "content",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matches to return",
                        "default": 50,
                    },
                },
                "required": ["pattern", "path"],
            },
        },
    },
]
