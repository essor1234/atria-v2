"""Built-in tool schemas: orchestration tools.

Auto-grouped from the former monolithic `definitions.py`. Each module exports a
`SCHEMAS` list of OpenAI-style function tool schema dicts.
"""

from __future__ import annotations

from typing import Any

from atria.core.agents.prompts.loader import load_tool_description

SCHEMAS: list[dict[str, Any]] = [
    # ===== Unified Solver Tools (divide + parallel behind a strategy param) =====
    {
        "type": "function",
        "function": {
            "name": "solve",
            "description": load_tool_description("solve"),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "string",
                        "enum": ["divide", "parallel"],
                        "description": (
                            "How to dispatch the work. 'divide' decomposes a request "
                            "into a DAG of interdependent sub-tasks run across module "
                            "workers and collects every result. 'parallel' fans out N "
                            "independent solvers on isolated git worktrees, then judges "
                            "the candidates and applies the winning diff."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "For strategy='parallel': the task each solver attempts "
                            "independently. For strategy='divide': accepted as an alias "
                            "of 'request'."
                        ),
                    },
                    "request": {
                        "type": "string",
                        "description": (
                            "For strategy='divide': the complex request to decompose "
                            "into sub-tasks."
                        ),
                    },
                    "module": {
                        "type": "string",
                        "description": (
                            "For strategy='divide': name of the module whose workflow "
                            "governs decomposition. Defaults to the active module."
                        ),
                    },
                    "n": {
                        "type": "integer",
                        "description": (
                            "For strategy='parallel': number of solvers. Clamped to "
                            "[2, max_solvers]. Defaults to the configured default."
                        ),
                    },
                },
                "required": ["strategy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_solve_result",
            "description": load_tool_description("get_solve_result"),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job_id returned by solve.",
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["divide", "parallel"],
                        "description": (
                            "Optional. The strategy used for this job; normally "
                            "inferred automatically from the job_id."
                        ),
                    },
                    "block": {
                        "type": "boolean",
                        "description": (
                            "Whether to wait for the job to complete. Set to false "
                            "for a non-blocking status check."
                        ),
                        "default": True,
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum wait time in milliseconds (max 600000).",
                        "default": 30000,
                        "maximum": 600000,
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    # ===== Batch Tool =====
    {
        "type": "function",
        "function": {
            "name": "batch_tool",
            "description": load_tool_description("batch_tool"),
            "parameters": {
                "type": "object",
                "properties": {
                    "invocations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {
                                    "type": "string",
                                    "description": "Name of the tool to invoke",
                                },
                                "input": {
                                    "type": "object",
                                    "description": "Arguments to pass to the tool",
                                },
                            },
                            "required": ["tool", "input"],
                        },
                        "description": "List of tool invocations to execute",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["parallel", "serial"],
                        "description": "Execution mode: 'parallel' (concurrent) or 'serial' (sequential)",
                        "default": "parallel",
                    },
                },
                "required": ["invocations"],
            },
        },
    },
    # ===== Plan Presentation Tool =====
    {
        "type": "function",
        "function": {
            "name": "present_plan",
            "description": load_tool_description("present_plan"),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_file_path": {
                        "type": "string",
                        "description": "Absolute path to the plan file to present for approval.",
                    },
                },
                "required": ["plan_file_path"],
            },
        },
    },
]
