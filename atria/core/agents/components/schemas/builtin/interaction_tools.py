"""Built-in tool schemas: interaction tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Notebook Edit Tool =====
    {
        "type": "function",
        "function": {
            "name": "notebook_edit",
            "description": load_tool_description("notebook_edit"),
            "parameters": {
                "type": "object",
                "properties": {
                    "notebook_path": {
                        "type": "string",
                        "description": "Absolute path to the Jupyter notebook file (.ipynb)",
                    },
                    "new_source": {
                        "type": "string",
                        "description": "New source content for the cell. Required for replace and insert modes.",
                    },
                    "cell_id": {
                        "type": "string",
                        "description": "ID of the cell to edit. For insert mode, new cell is inserted after this cell.",
                    },
                    "cell_number": {
                        "type": "integer",
                        "description": "0-indexed cell position. Alternative to cell_id. For insert mode, new cell is inserted at this position.",
                    },
                    "cell_type": {
                        "type": "string",
                        "enum": ["code", "markdown"],
                        "description": "Cell type. Required for insert mode, optional for replace mode.",
                    },
                    "edit_mode": {
                        "type": "string",
                        "enum": ["replace", "insert", "delete"],
                        "default": "replace",
                        "description": "Operation type: replace (update existing cell), insert (add new cell), or delete (remove cell).",
                    },
                },
                "required": ["notebook_path", "new_source"],
            },
        },
    },
    # ===== Ask User Question Tool =====
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": load_tool_description("ask_user"),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "description": "List of questions to ask (1-4 questions)",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "description": "The complete question to ask. Should be clear and end with a question mark.",
                                },
                                "header": {
                                    "type": "string",
                                    "description": "Short label displayed as a chip/tag (max 12 chars). E.g., 'Auth method', 'Library'.",
                                    "maxLength": 12,
                                },
                                "options": {
                                    "type": "array",
                                    "description": "Available choices (2-4 options). An 'Other' option is added automatically.",
                                    "minItems": 2,
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "description": "Display text for the option (1-5 words).",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "Explanation of what this option means or implies.",
                                            },
                                        },
                                        "required": ["label", "description"],
                                    },
                                },
                                "multiSelect": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "If true, allow selecting multiple options instead of just one.",
                                },
                            },
                            "required": ["question", "header", "options"],
                        },
                    },
                },
                "required": ["questions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_todos",
            "description": load_tool_description("write_todos"),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "List of todo items to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {
                                    "type": "string",
                                    "description": "Plain text task description. No markdown formatting.",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "Task status. Defaults to 'pending'.",
                                    "default": "pending",
                                },
                                "activeForm": {
                                    "type": "string",
                                    "description": "Present continuous form shown during execution (e.g., 'Running tests')",
                                },
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": load_tool_description("update_todo"),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the to-do to update (shown in the panel).",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for this to-do item.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["todo", "doing", "done"],
                        "description": "Set to 'doing' when you start, 'done' when you finish.",
                    },
                    "log": {
                        "type": "string",
                        "description": "Append a log entry while working on this task.",
                    },
                    "expanded": {
                        "type": "boolean",
                        "description": "Show or hide logs beneath this to-do.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_todo",
            "description": load_tool_description("complete_todo"),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "ID of the to-do item to mark complete.",
                    },
                    "log": {
                        "type": "string",
                        "description": "Optional completion note.",
                    },
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": load_tool_description("list_todos"),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_todos",
            "description": load_tool_description("clear_todos"),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
