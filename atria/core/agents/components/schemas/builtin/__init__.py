"""Built-in tool schemas, grouped by domain.

The schemas were historically a single ~1600-line list in ``definitions.py``.
They are now split into focused modules (one ``SCHEMAS`` list each) and
reassembled here, in their original order, as ``BUILTIN_TOOL_SCHEMAS``.
"""

from __future__ import annotations

from typing import Any

from .agent_tools import SCHEMAS as _AGENT
from .artifact_tools import SCHEMAS as _ARTIFACT
from .browser_media_tools import SCHEMAS as _BROWSER_MEDIA
from .file_tools import SCHEMAS as _FILE
from .interaction_tools import SCHEMAS as _INTERACTION
from .knowledge_tools import SCHEMAS as _KNOWLEDGE
from .orchestration_tools import SCHEMAS as _ORCHESTRATION
from .process_tools import SCHEMAS as _PROCESS
from .symbol_tools import SCHEMAS as _SYMBOL
from .system_tools import SCHEMAS as _SYSTEM
from .web_tools import SCHEMAS as _WEB
from .component_tools import SCHEMAS as _COMPONENT

# Order preserved from the original monolithic definition.
BUILTIN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    *_FILE,
    *_PROCESS,
    *_WEB,
    *_INTERACTION,
    *_BROWSER_MEDIA,
    *_SYSTEM,
    *_SYMBOL,
    *_KNOWLEDGE,
    *_AGENT,
    *_ORCHESTRATION,
    *_ARTIFACT,
    *_COMPONENT,
]

__all__ = ["BUILTIN_TOOL_SCHEMAS"]
