"""Built-in tool schemas: browser media tools.

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
            "name": "open_browser",
            "description": load_tool_description("open_browser"),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL or file path to open in the browser. Supports: full URLs (http://example.com), localhost addresses (localhost:3000), and local file paths (index.html, ./app.html, /path/to/file.html). Local files are automatically converted to file:// URLs.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_screenshot",
            "description": load_tool_description("capture_screenshot"),
            "parameters": {
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "Monitor number to capture (default: 1 for primary monitor)",
                        "default": 1,
                    },
                    "region": {
                        "type": "object",
                        "description": "Optional region to capture (x, y, width, height). If not provided, captures full screen.",
                        "properties": {
                            "x": {"type": "integer", "description": "X coordinate"},
                            "y": {"type": "integer", "description": "Y coordinate"},
                            "width": {"type": "integer", "description": "Width in pixels"},
                            "height": {"type": "integer", "description": "Height in pixels"},
                        },
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": load_tool_description("analyze_image"),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text prompt describing what to analyze in the image (e.g., 'Describe this image', 'What errors do you see?', 'Extract text from this image')",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "Path to local image file (relative to working directory or absolute). Supports .jpg, .jpeg, .png, .gif, .webp. Takes precedence over image_url if both provided.",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "URL of online image (must start with http:// or https://). Used only if image_path not provided.",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum tokens in response (optional, defaults to config value)",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_web_screenshot",
            "description": load_tool_description("capture_web_screenshot"),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the web page to capture (must start with http:// or https://)",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional path to save screenshot (relative to working directory or absolute). If not provided, auto-generates filename in temp directory. For PDF, the .pdf extension will be automatically used.",
                    },
                    "capture_pdf": {
                        "type": "boolean",
                        "description": "If true, also capture a PDF version of the page. PDF is more reliable for very long pages. Both screenshot and PDF will be saved if enabled. Default: false",
                        "default": False,
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "Maximum time to wait for page load in milliseconds. Default: 90000 (90 seconds). Complex sites with heavy JavaScript (like SaaS platforms, dashboards) may need 120000-180000ms.",
                        "default": 90000,
                    },
                    "viewport_width": {
                        "type": "integer",
                        "description": "Browser viewport width in pixels. Default: 1920",
                        "default": 1920,
                    },
                    "viewport_height": {
                        "type": "integer",
                        "description": "Browser viewport height in pixels. Default: 1080",
                        "default": 1080,
                    },
                },
                "required": ["url"],
            },
        },
    },
    # ===== Browser Automation Tool =====
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": load_tool_description("browser"),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "navigate",
                            "click",
                            "type",
                            "fill",
                            "screenshot",
                            "get_text",
                            "wait",
                            "evaluate",
                            "tabs_list",
                            "tab_close",
                            "back",
                            "forward",
                            "reload",
                        ],
                        "description": "Browser action to perform",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target for the action: URL (navigate), CSS selector (click/type/fill/wait/get_text/screenshot), tab index (tab_close), or JS expression (evaluate)",
                    },
                    "value": {
                        "type": "string",
                        "description": "Value for the action: text (type/fill) or JavaScript code (evaluate)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Action timeout in milliseconds (default: 10000)",
                        "default": 10000,
                    },
                },
                "required": ["action"],
            },
        },
    },
]
