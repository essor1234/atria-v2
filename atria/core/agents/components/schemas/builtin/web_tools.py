"""Built-in tool schemas: web tools.

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
            "name": "fetch_url",
            "description": load_tool_description("fetch_url"),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch (must start with http:// or https://)",
                    },
                    "extract_text": {
                        "type": "boolean",
                        "description": "Whether to extract text from HTML (default: true)",
                        "default": True,
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum content length in characters (default: 50000)",
                        "default": 50000,
                    },
                    "deep_crawl": {
                        "type": "boolean",
                        "description": "Follow links and crawl multiple pages starting from the seed URL.",
                        "default": False,
                    },
                    "crawl_strategy": {
                        "type": "string",
                        "enum": ["bfs", "dfs", "best_first"],
                        "description": "Traversal strategy when deep_crawl is true. best_first (default) prioritizes relevance, bfs covers broadly, dfs follows a single branch.",
                        "default": "best_first",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum depth (beyond the seed page) to crawl when deep_crawl is enabled. Depth 0 is the starting page. Defaults to 1.",
                        "default": 1,
                    },
                    "include_external": {
                        "type": "boolean",
                        "description": "Allow crawling links that leave the starting domain when deep_crawl is enabled.",
                        "default": False,
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Optional cap on the total number of pages to crawl when deep_crawl is enabled.",
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional allow-list of domains to keep while deep crawling.",
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional block-list of domains to skip while deep crawling.",
                    },
                    "url_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional glob-style URL patterns the crawler must match (e.g., '*docs*').",
                    },
                    "stream": {
                        "type": "boolean",
                        "description": "When true (and deep_crawl is enabled) stream pages as they are discovered before aggregation.",
                        "default": False,
                    },
                },
                "required": ["url"],
            },
        },
    },
    # ===== Web Search Tool =====
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": load_tool_description("web_search"),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to use. Be specific and include relevant keywords.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10)",
                        "default": 10,
                    },
                    "allowed_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Only include search results from these domains (e.g., ['docs.python.org', 'stackoverflow.com'])",
                    },
                    "blocked_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Never include search results from these domains",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # ===== Send Image Tool (web UI) =====
    {
        "type": "function",
        "function": {
            "name": "send_image",
            "description": (
                "Send an image to the web UI chat as a standalone image bubble. "
                "Provide either a local server-side absolute path OR a remote http(s) URL — "
                "never both, never neither. Use for screenshots, generated charts, diagrams, "
                "or any visual the user should see. Only works in the web UI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Absolute server-side path to a local image file "
                            "(PNG/JPEG/GIF/WebP/SVG, ≤10 MB)."
                        ),
                    },
                    "url": {
                        "type": "string",
                        "description": "Public http(s) URL of a remote image.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption shown below the image.",
                    },
                },
                "required": [],
            },
        },
    },
    # Skill-owned schemas live in their skill folders and are merged in via
    # ToolSchemaBuilder(extra_schemas=...).
    {
        "type": "function",
        "function": {
            "name": "md_to_pdf",
            "description": load_tool_description("md-to-pdf"),
            "parameters": {
                "type": "object",
                "properties": {
                    "md_path": {"type": "string"},
                    "pdf_path": {"type": "string"},
                },
                "required": ["md_path", "pdf_path"],
            },
        },
    },
]
