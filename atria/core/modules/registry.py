"""In-memory module registry. Versioned so prompt builders can detect changes."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Dict, List

from atria.core.modules import store
from atria.core.modules.store import Module, ModuleNotFound
from atria.core.paths import atria_dir

logger = logging.getLogger(__name__)


def resolve_modules_root() -> Path:
    """Discover the modules directory.

    Priority:
      1. ``ATRIA_MODULES_DIR`` env var (absolute or relative to CWD).
      2. ``<cwd>/modules`` if it exists — top-level, source-tracked.
      3. ``<cwd>/.atria/modules`` (project-local hidden convention).
      4. ``~/.atria/modules`` (legacy user-global fallback).

    The resolved directory is created on first use.
    """
    env = os.environ.get("ATRIA_MODULES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd_modules = Path.cwd() / "modules"
    if cwd_modules.is_dir():
        return cwd_modules.resolve()
    cwd_project = Path.cwd() / ".atria"
    if cwd_project.is_dir():
        return (cwd_project / "modules").resolve()
    return (atria_dir() / "modules").resolve()


class ModuleRegistry:
    """Thread-safe in-memory registry of file-based modules."""

    def __init__(self, root: Path):
        self.root = root
        self._modules: Dict[str, Module] = {}
        self._version: int = 0
        self._lock = threading.Lock()

    @property
    def version(self) -> int:
        return self._version

    def load_all(self) -> None:
        """Replace contents with everything currently on disk. Bumps version."""
        with self._lock:
            self._modules = {m.name: m for m in store.list_modules(self.root)}
            self._version += 1
        logger.info(
            "module registry: loaded %d module(s) (v=%d)", len(self._modules), self._version
        )

    def reload_one(self, name: str) -> None:
        """Reload a single module from disk. If gone, remove it. Bumps version."""
        with self._lock:
            try:
                self._modules[name] = store.read_module(self.root, name)
            except ModuleNotFound:
                self._modules.pop(name, None)
            self._version += 1

    def remove(self, name: str) -> None:
        with self._lock:
            self._modules.pop(name, None)
            self._version += 1

    def all(self) -> List[Module]:
        with self._lock:
            return [self._modules[n] for n in sorted(self._modules)]

    def names(self) -> List[str]:
        with self._lock:
            return sorted(self._modules)

    def get(self, name: str) -> Module:
        with self._lock:
            return self._modules[name]


_GLOBAL: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    """Return the process-wide registry.

    Root is resolved by :func:`resolve_modules_root` — project ``.atria/modules``
    takes precedence over the user-global ``~/.atria/modules``.
    """
    global _GLOBAL
    if _GLOBAL is None:
        root = resolve_modules_root()
        root.mkdir(parents=True, exist_ok=True)
        logger.info("module registry rooted at: %s", root)
        _GLOBAL = ModuleRegistry(root)
        _GLOBAL.load_all()
    return _GLOBAL


def reset_registry_for_tests() -> None:
    """Test helper: clear the process-wide registry singleton."""
    global _GLOBAL
    _GLOBAL = None
