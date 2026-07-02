"""In-memory module registry. Versioned so prompt builders can detect changes."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Dict, List

from atria.core.modules import store
from atria.core.modules.deps import install_module_deps
from atria.core.modules.store import Module, ModuleNotFound
from atria.core.paths import atria_dir

logger = logging.getLogger(__name__)


def load_disabled_modules() -> set[str]:
    """Names to exclude from discovery, read from ``ATRIA_DISABLED_MODULES``.

    Comma- or whitespace-separated list of module folder names, or ``*`` /
    ``all`` to disable every module. This is a true kill switch — disabled
    modules never enter the registry, so they stay off the prompt catalog,
    subagent routing, and dependency install — while their folder remains
    untouched on disk. Empty/unset means nothing is disabled.
    """
    raw = os.environ.get("ATRIA_DISABLED_MODULES", "")
    return {tok for tok in re.split(r"[,\s]+", raw) if tok}


def _all_modules_disabled(disabled: set[str]) -> bool:
    """True when the env requests disabling every module (``*`` or ``all``)."""
    return "*" in disabled or "all" in disabled


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
        disabled = load_disabled_modules()
        skip_all = _all_modules_disabled(disabled)
        with self._lock:
            modules = (
                []
                if skip_all
                else [m for m in store.list_modules(self.root) if m.name not in disabled]
            )
            for m in modules:
                install_module_deps(m.dir)
            self._modules = {m.name: m for m in modules}
            self._version += 1
        logger.info(
            "module registry: loaded %d module(s) (v=%d, %d disabled via env)",
            len(self._modules),
            self._version,
            len(disabled),
        )

    def reload_one(self, name: str) -> None:
        """Reload a single module from disk. If gone or disabled, remove it. Bumps version."""
        disabled = load_disabled_modules()
        if name in disabled or _all_modules_disabled(disabled):
            self.remove(name)
            return
        with self._lock:
            try:
                module = store.read_module(self.root, name)
                install_module_deps(module.dir)
                self._modules[name] = module
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
