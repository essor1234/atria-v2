"""FastAPI dependency: return the process-wide module registry."""

from __future__ import annotations

from atria.core.modules.registry import ModuleRegistry, get_registry


def get_modules_registry() -> ModuleRegistry:
    return get_registry()
