"""Backwards-compatible re-exports for the Docker tool handler/registry.

The implementation was split into :mod:`runtime_handler` (DockerToolHandler) and
:mod:`tool_registry` (DockerToolRegistry); this module preserves the original
``atria.core.docker.tool_handler`` import path.
"""

from __future__ import annotations

from .runtime_handler import DockerToolHandler, _run_async
from .tool_registry import DockerToolRegistry

__all__ = ["DockerToolHandler", "DockerToolRegistry", "_run_async"]
