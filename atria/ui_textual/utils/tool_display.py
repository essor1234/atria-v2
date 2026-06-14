"""Compatibility shim — canonical implementation moved to atria.core.utils.tool_display."""
from atria.core.utils.tool_display import *  # noqa: F401, F403
from atria.core.utils.tool_display import (
    PATH_ARG_KEYS,
    format_tool_call,
    get_tool_display_parts,
    summarize_tool_arguments,
    build_tool_call_text,
    _TOOL_DISPLAY_PARTS,
)
