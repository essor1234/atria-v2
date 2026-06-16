# File-Based Modules Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the DB-backed module system (modules + tools + tasks + Flowgram workflow editor) with a file-based system: each module is a folder under `~/.atria/modules/<name>/` containing `SKILL.md` and `script.py`. SKILL.md is auto-injected into every conversation's system prompt; scripts are run by the agent via the existing bash tool. UI surfaces modules inside the Artifact Viewer.

**Architecture:** Backend rewrites `atria/core/modules/` to a tiny store/registry/watcher trio, exposes a flat CRUD REST API, and replaces the `_module_skill_md` hook in `agent_executor.py` with a `build_skill_block(registry)` call that returns concatenated SKILL.md contents. A `watchdog`-based observer auto-reloads on disk changes and broadcasts a `modules.changed` WS event. The frontend deletes `web-ui/src/pages/modules/` entirely and adds a left-pane mode switcher (Files | Modules) inside the Artifact Viewer; selecting a module opens a new `module-editor` viewer tab with two CodeMirror panes.

**Tech Stack:** Python (FastAPI, watchdog, pytest), React + TypeScript + Zustand + CodeMirror + Tailwind, SQLite (only to drop the legacy tables).

**Per-project convention (from user memory):** Do not run pytest per task; write tests as part of each task and run the full suite once at the very end (Task 11). Commit messages **must not** include any `Co-Authored-By: Claude` trailer.

---

## File Structure

**New (backend):**
- `atria/core/modules/__init__.py` — re-exports
- `atria/core/modules/store.py` — filesystem read/write helpers
- `atria/core/modules/registry.py` — in-memory `dict[str, Module]` + version counter
- `atria/core/modules/watcher.py` — watchdog observer + debounced reload + WS broadcast hook
- `atria/core/modules/prompt.py` — `build_skill_block(registry) -> str`
- `atria/web/routes/modules.py` — **rewritten** flat CRUD router
- `atria/web/dependencies/modules.py` — **rewritten**: returns the global registry
- `tests/test_modules_store.py`
- `tests/test_modules_registry.py`
- `tests/test_modules_watcher.py`
- `tests/test_modules_prompt.py`
- `tests/test_modules_routes.py`

**New (frontend):**
- `web-ui/src/components/ArtifactViewer/LeftPaneTabs.tsx` — Files | Modules switcher
- `web-ui/src/components/ArtifactViewer/ModuleList.tsx` — sidebar list + New button
- `web-ui/src/components/ArtifactViewer/viewers/ModuleEditor.tsx` — two-pane editor
- `web-ui/src/stores/modules.ts` — Zustand store, WS-subscribed
- `web-ui/src/api/modules.ts` — typed REST client

**Modified:**
- `atria/web/agent_executor.py` — swap DB-backed module loading for `build_skill_block(registry)`
- `atria/core/agents/prompts/composition.py` *(none — block injected at stable-prefix in agent_executor as today)*
- `atria/web/server.py` — start watcher on lifespan startup, register new router
- `atria/web/websocket.py` — no code change; new `modules.changed` event uses existing `broadcast()`
- `atria/db/connection.py` — add startup `DROP TABLE` for legacy `modules`, `module_tools`, `module_tasks`
- `atria/db/models.py` — remove the three legacy ORM models
- `pyproject.toml` / `requirements.txt` — add `watchdog>=4.0`
- `web-ui/src/App.tsx` — remove `/modules*` routes and lazy imports
- `web-ui/src/components/Layout/TopBar.tsx` — remove Modules nav link
- `web-ui/src/components/ArtifactViewer/ArtifactViewer.tsx` — wrap left pane with `LeftPaneTabs`
- `web-ui/src/components/ArtifactViewer/viewers/index.tsx` — dispatch `module-editor` tab kind
- `web-ui/src/stores/viewerTabs.ts` — allow `ViewerTab` with `kind: 'module'` (no path)
- `web-ui/src/types/index.ts` — extend `ViewerTab` type
- `web-ui/src/stores/chat.ts` — handle `modules.changed` WS event (delegate to modules store)

**Deleted:**
- `atria/core/modules/builtins/` (folder)
- `atria/core/modules/executor/` (folder)
- `atria/core/modules/loader.py`, `seed.py`, `models.py`, `registry.py` *(old)*
- `atria/db/repositories/modules_repo.py`
- `atria/repl/commands/modules_commands.py`
- `web-ui/src/pages/modules/` (entire folder)
- `web-ui/src/components/ModulePicker.tsx`
- Any imports of the deleted symbols (`ModulesRepository`, `ModuleLoader`, `ToolRegistry`, `reset_module`, `_adapt_module_callables`, `validate`, `TaskValidationError`)

---

## Task 1: Add watchdog dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

- [ ] **Step 1: Add `watchdog>=4.0` to `pyproject.toml`**

Find the `[project]` `dependencies = [...]` array in `pyproject.toml` and add the entry alphabetically:

```toml
"watchdog>=4.0",
```

- [ ] **Step 2: Add `watchdog>=4.0` to `requirements.txt`**

Append a new line at the bottom:

```
watchdog>=4.0
```

- [ ] **Step 3: Install the new dependency**

Run:

```bash
uv pip install "watchdog>=4.0"
```

Expected: a line like `Installed N package(s)` referencing watchdog (or `already satisfied`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "chore(modules): add watchdog dependency for filesystem watcher"
```

---

## Task 2: Delete legacy module system (backend)

**Files:**
- Delete: `atria/core/modules/executor/` (folder)
- Delete: `atria/core/modules/builtins/` (folder)
- Delete: `atria/core/modules/loader.py`
- Delete: `atria/core/modules/seed.py`
- Delete: `atria/core/modules/models.py`
- Delete: `atria/core/modules/registry.py`
- Delete: `atria/db/repositories/modules_repo.py`
- Delete: `atria/repl/commands/modules_commands.py`
- Delete: `atria/web/routes/modules.py` (will be re-created in Task 7)
- Delete: `atria/web/dependencies/modules.py` (will be re-created in Task 7)
- Modify: `atria/core/modules/__init__.py` (empty placeholder for now)
- Modify: `atria/db/models.py` (remove three legacy ORM classes)
- Modify: `atria/web/server.py` (remove modules router include)
- Modify: `atria/web/agent_executor.py` (remove DB-module loading block)
- Modify: `atria/web/dependencies/__init__.py` (remove `get_module_loader` re-export)
- Modify: any REPL command index referencing `modules_commands`
- Modify: `atria/core/agents/main_agent/agent.py` (remove `_adapt_module_callables` if defined there)

- [ ] **Step 1: Delete the folders and files**

```bash
rm -rf atria/core/modules/executor atria/core/modules/builtins
rm -f atria/core/modules/loader.py atria/core/modules/seed.py atria/core/modules/models.py atria/core/modules/registry.py
rm -f atria/db/repositories/modules_repo.py
rm -f atria/repl/commands/modules_commands.py
rm -f atria/web/routes/modules.py
rm -f atria/web/dependencies/modules.py
```

- [ ] **Step 2: Replace `atria/core/modules/__init__.py` with a placeholder**

Overwrite the file with exactly:

```python
"""File-based modules. See store.py / registry.py / watcher.py / prompt.py."""
```

- [ ] **Step 3: Remove the three legacy ORM models from `atria/db/models.py`**

Open `atria/db/models.py`, find the `Module`, `ModuleTool`, `ModuleTask` class definitions and delete them along with any related `relationship(...)` references on other models that point to them. Also delete any module-related imports at the top of the file that are no longer used.

- [ ] **Step 4: Remove the modules router include from `atria/web/server.py`**

In `atria/web/server.py`, find any `from atria.web.routes.modules import router as modules_router` import and the corresponding `app.include_router(modules_router)` call. Delete both lines. (We will re-add the new router in Task 7.)

- [ ] **Step 5: Remove the DB-module loading block from `atria/web/agent_executor.py`**

In `atria/web/agent_executor.py`, locate the block starting near line 398 with the comment `# Load active module (if any) ...` and ending after the `if _module_skill_md:` block that appends to `system_content`. Delete this entire block (including the `_module_skill_md = ""` and `_active_module_id = ...` assignments and the `try/except` that calls `_loader.load(...)`).

Also delete the now-unused `skill_block` append section — the new replacement is wired in Task 8.

Verify these symbols are no longer referenced anywhere in this file: `get_module_loader`, `_adapt_module_callables`, `ModulesRepository`, `active_module_id`. Remove their imports.

- [ ] **Step 6: Clean up the `atria/web/dependencies/__init__.py` re-exports**

Open `atria/web/dependencies/__init__.py`. Remove any line referencing `get_module_loader` or anything from the deleted `dependencies/modules.py`.

- [ ] **Step 7: Remove `_adapt_module_callables` if it lives in main_agent/agent.py**

Open `atria/core/agents/main_agent/agent.py`. If a function `_adapt_module_callables` is defined there, delete it. Remove any imports it relied on that are now unused.

- [ ] **Step 8: Clean up the REPL command index**

Open `atria/repl/commands/__init__.py` (or whichever file aggregates command registrations). Remove the import of `modules_commands` and any registration calls that use it.

- [ ] **Step 9: Commit**

```bash
git add -A atria
git commit -m "feat(modules)!: remove DB-backed module system (Flowgram, executor, tools, tasks)"
```

---

## Task 3: Drop legacy DB tables on startup

**Files:**
- Modify: `atria/db/connection.py`

- [ ] **Step 1: Add table drops alongside the existing `ALTER TABLE conversations` migration**

Open `atria/db/connection.py` and find the `ALTER TABLE conversations` block near line 93. Below the existing migration code (still inside the same startup-migration function), add:

```python
# Legacy modules system removed; drop its tables if present.
for _legacy in ("module_tasks", "module_tools", "modules"):
    try:
        conn.execute(text(f"DROP TABLE IF EXISTS {_legacy}"))
    except Exception as _drop_err:
        logger.warning("Failed to drop legacy table %s: %s", _legacy, _drop_err)
```

If `text` is not already imported in this file, add `from sqlalchemy import text` to the imports. If `logger` is not defined, use the existing logging idiom already in the file.

(Drop order is child → parent; SQLite has no FK enforcement by default but the order is correct regardless.)

- [ ] **Step 2: Commit**

```bash
git add atria/db/connection.py
git commit -m "feat(modules): drop legacy modules/module_tools/module_tasks tables on startup"
```

---

## Task 4: Implement `store.py` (filesystem CRUD)

**Files:**
- Create: `atria/core/modules/store.py`
- Create: `tests/test_modules_store.py`

- [ ] **Step 1: Write `tests/test_modules_store.py`**

```python
"""Tests for the filesystem-backed module store."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from atria.core.modules.store import (
    MODULE_NAME_RE,
    Module,
    InvalidModuleName,
    ModuleExists,
    ModuleNotFound,
    create_module,
    delete_module,
    list_modules,
    read_module,
    update_module,
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "modules"


def test_name_regex_accepts_valid_and_rejects_invalid():
    assert MODULE_NAME_RE.fullmatch("my_module-1")
    assert not MODULE_NAME_RE.fullmatch("Bad Name")
    assert not MODULE_NAME_RE.fullmatch("../escape")


def test_create_and_read_module(root: Path):
    m = create_module(root, "demo")
    assert isinstance(m, Module)
    assert m.name == "demo"
    assert "# demo" in m.skill_md
    assert "if __name__" in m.script_py
    assert (root / "demo" / "SKILL.md").is_file()
    assert (root / "demo" / "script.py").is_file()
    assert read_module(root, "demo").skill_md == m.skill_md


def test_create_rejects_invalid_name(root: Path):
    with pytest.raises(InvalidModuleName):
        create_module(root, "Bad Name")


def test_create_rejects_existing(root: Path):
    create_module(root, "demo")
    with pytest.raises(ModuleExists):
        create_module(root, "demo")


def test_update_writes_both_files_atomically(root: Path):
    create_module(root, "demo")
    update_module(root, "demo", skill_md="# new", script_py="print('hi')\n")
    m = read_module(root, "demo")
    assert m.skill_md == "# new"
    assert m.script_py == "print('hi')\n"
    # No leftover temp files
    leftovers = [p for p in (root / "demo").iterdir() if p.name.startswith(".tmp-")]
    assert leftovers == []


def test_update_missing_raises(root: Path):
    with pytest.raises(ModuleNotFound):
        update_module(root, "nope", skill_md="x", script_py="y")


def test_delete_removes_folder(root: Path):
    create_module(root, "demo")
    delete_module(root, "demo")
    assert not (root / "demo").exists()


def test_list_modules_sorted_and_skips_malformed(root: Path):
    create_module(root, "bravo")
    create_module(root, "alpha")
    # Malformed: a folder missing SKILL.md
    (root / "broken").mkdir()
    (root / "broken" / "script.py").write_text("pass\n")
    names = [m.name for m in list_modules(root)]
    assert names == ["alpha", "bravo"]


def test_list_creates_root_if_missing(root: Path):
    assert not root.exists()
    assert list_modules(root) == []
    assert root.exists()
```

- [ ] **Step 2: Implement `atria/core/modules/store.py`**

```python
"""Filesystem-backed CRUD for modules.

A module is a folder ``<root>/<name>/`` containing ``SKILL.md`` and ``script.py``.
Only these two files are considered part of the editable surface, but sibling
files are tolerated (the script may read them).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


MODULE_NAME_RE = re.compile(r"[a-z0-9_-]+")
SKILL_FILE = "SKILL.md"
SCRIPT_FILE = "script.py"


class InvalidModuleName(ValueError):
    """Raised when a module name contains disallowed characters."""


class ModuleExists(FileExistsError):
    """Raised when creating a module that already exists."""


class ModuleNotFound(FileNotFoundError):
    """Raised when reading/updating/deleting a module that does not exist."""


@dataclass
class Module:
    name: str
    skill_md: str
    script_py: str
    dir: Path
    mtime: float


def _validate_name(name: str) -> None:
    if not MODULE_NAME_RE.fullmatch(name):
        raise InvalidModuleName(
            f"module name {name!r} must match [a-z0-9_-]+ (no spaces, slashes, or uppercase)"
        )


def _module_dir(root: Path, name: str) -> Path:
    _validate_name(name)
    return root / name


def _ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)


def _starter_skill_md(name: str) -> str:
    return (
        f"# {name}\n\n"
        "Describe what this module does and when to use it.\n\n"
        "## Usage\n\n"
        f"Run via the bash tool: `python ~/.atria/modules/{name}/script.py`\n"
    )


def _starter_script_py() -> str:
    return (
        "#!/usr/bin/env python\n"
        '"""Entry point for this module."""\n\n'
        "from __future__ import annotations\n\n\n"
        "def main() -> None:\n"
        '    print("hello from module")\n\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(f".tmp-{path.name}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _read_module(root: Path, name: str) -> Module:
    d = _module_dir(root, name)
    skill_path = d / SKILL_FILE
    script_path = d / SCRIPT_FILE
    if not skill_path.is_file() or not script_path.is_file():
        raise ModuleNotFound(name)
    return Module(
        name=name,
        skill_md=skill_path.read_text(encoding="utf-8"),
        script_py=script_path.read_text(encoding="utf-8"),
        dir=d,
        mtime=max(skill_path.stat().st_mtime, script_path.stat().st_mtime),
    )


def list_modules(root: Path) -> List[Module]:
    """List all valid modules under ``root`` sorted by name. Creates ``root`` if missing."""
    _ensure_root(root)
    out: List[Module] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            _validate_name(entry.name)
        except InvalidModuleName:
            logger.warning("skipping module folder with invalid name: %s", entry.name)
            continue
        try:
            out.append(_read_module(root, entry.name))
        except ModuleNotFound:
            logger.warning("skipping malformed module folder (missing SKILL.md or script.py): %s", entry.name)
    return out


def read_module(root: Path, name: str) -> Module:
    _ensure_root(root)
    return _read_module(root, name)


def create_module(root: Path, name: str, *, skill_md: str | None = None, script_py: str | None = None) -> Module:
    _ensure_root(root)
    d = _module_dir(root, name)
    if d.exists():
        raise ModuleExists(name)
    d.mkdir()
    _atomic_write(d / SKILL_FILE, skill_md or _starter_skill_md(name))
    _atomic_write(d / SCRIPT_FILE, script_py if script_py is not None else _starter_script_py())
    return _read_module(root, name)


def update_module(root: Path, name: str, *, skill_md: str, script_py: str) -> Module:
    _ensure_root(root)
    d = _module_dir(root, name)
    if not d.is_dir():
        raise ModuleNotFound(name)
    _atomic_write(d / SKILL_FILE, skill_md)
    _atomic_write(d / SCRIPT_FILE, script_py)
    return _read_module(root, name)


def delete_module(root: Path, name: str) -> None:
    _ensure_root(root)
    d = _module_dir(root, name)
    if not d.is_dir():
        raise ModuleNotFound(name)
    shutil.rmtree(d)
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/modules/store.py tests/test_modules_store.py
git commit -m "feat(modules): filesystem-backed module store"
```

---

## Task 5: Implement `registry.py` (in-memory + version counter)

**Files:**
- Create: `atria/core/modules/registry.py`
- Create: `tests/test_modules_registry.py`

- [ ] **Step 1: Write `tests/test_modules_registry.py`**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from atria.core.modules import store
from atria.core.modules.registry import ModuleRegistry


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "modules"


def test_load_all_populates_from_disk(root: Path):
    store.create_module(root, "alpha")
    store.create_module(root, "beta")
    reg = ModuleRegistry(root)
    reg.load_all()
    assert sorted(reg.names()) == ["alpha", "beta"]
    assert reg.version == 1


def test_reload_one_updates_in_place_and_bumps_version(root: Path):
    store.create_module(root, "alpha")
    reg = ModuleRegistry(root)
    reg.load_all()
    v0 = reg.version
    store.update_module(root, "alpha", skill_md="# changed", script_py="x\n")
    reg.reload_one("alpha")
    assert reg.get("alpha").skill_md == "# changed"
    assert reg.version == v0 + 1


def test_reload_one_for_deleted_module_removes_it(root: Path):
    store.create_module(root, "alpha")
    reg = ModuleRegistry(root)
    reg.load_all()
    store.delete_module(root, "alpha")
    reg.reload_one("alpha")
    assert "alpha" not in reg.names()


def test_remove_explicit(root: Path):
    store.create_module(root, "alpha")
    reg = ModuleRegistry(root)
    reg.load_all()
    v = reg.version
    reg.remove("alpha")
    assert "alpha" not in reg.names()
    assert reg.version == v + 1


def test_all_returns_sorted_list(root: Path):
    store.create_module(root, "bravo")
    store.create_module(root, "alpha")
    reg = ModuleRegistry(root)
    reg.load_all()
    assert [m.name for m in reg.all()] == ["alpha", "bravo"]
```

- [ ] **Step 2: Implement `atria/core/modules/registry.py`**

```python
"""In-memory module registry. Versioned so prompt builders can detect changes."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List

from atria.core.modules import store
from atria.core.modules.store import Module, ModuleNotFound

logger = logging.getLogger(__name__)


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
        logger.info("module registry: loaded %d module(s) (v=%d)", len(self._modules), self._version)

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
    """Return the process-wide registry, defaulting to ``~/.atria/modules``."""
    global _GLOBAL
    if _GLOBAL is None:
        root = Path.home() / ".atria" / "modules"
        _GLOBAL = ModuleRegistry(root)
        _GLOBAL.load_all()
    return _GLOBAL


def reset_registry_for_tests() -> None:
    """Test helper: clear the process-wide registry singleton."""
    global _GLOBAL
    _GLOBAL = None
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/modules/registry.py tests/test_modules_registry.py
git commit -m "feat(modules): in-memory module registry with version counter"
```

---

## Task 6: Implement `prompt.py` (SKILL block builder)

**Files:**
- Create: `atria/core/modules/prompt.py`
- Create: `tests/test_modules_prompt.py`

- [ ] **Step 1: Write `tests/test_modules_prompt.py`**

```python
from __future__ import annotations

from pathlib import Path

import pytest

from atria.core.modules import store
from atria.core.modules.prompt import build_skill_block
from atria.core.modules.registry import ModuleRegistry


@pytest.fixture()
def reg(tmp_path: Path) -> ModuleRegistry:
    root = tmp_path / "modules"
    store.create_module(root, "alpha", skill_md="# alpha\n\nDoes alpha things.\n")
    store.create_module(root, "bravo", skill_md="# bravo\n\nDoes bravo things.\n")
    r = ModuleRegistry(root)
    r.load_all()
    return r


def test_empty_registry_returns_empty_string(tmp_path: Path):
    r = ModuleRegistry(tmp_path / "empty")
    r.load_all()
    assert build_skill_block(r) == ""


def test_block_contains_header_and_each_module_sorted(reg: ModuleRegistry):
    out = build_skill_block(reg)
    assert "## Active Module Skills" in out
    assert "python ~/.atria/modules/<name>/script.py" in out
    # Module sections appear in sorted order
    assert out.index("### alpha") < out.index("### bravo")
    assert "Does alpha things." in out
    assert "Does bravo things." in out
```

- [ ] **Step 2: Implement `atria/core/modules/prompt.py`**

```python
"""Build the SKILL block injected into every conversation's system prompt."""
from __future__ import annotations

from atria.core.modules.registry import ModuleRegistry


_HEADER = (
    "## Active Module Skills\n\n"
    "The following modules are installed locally. Each module is a self-contained "
    "skill with a runnable Python script. To execute a module, run via the bash tool:\n\n"
    "    python ~/.atria/modules/<name>/script.py\n\n"
    "Each module's SKILL.md follows; treat it as authoritative for how to invoke that module.\n"
)


def build_skill_block(registry: ModuleRegistry) -> str:
    """Return the SKILL block (header + every module's SKILL.md). Empty if no modules."""
    modules = registry.all()
    if not modules:
        return ""
    parts = [_HEADER]
    for m in modules:
        parts.append(f"### {m.name}\n\n{m.skill_md.strip()}\n")
    return "\n".join(parts)
```

- [ ] **Step 3: Commit**

```bash
git add atria/core/modules/prompt.py tests/test_modules_prompt.py
git commit -m "feat(modules): build SKILL block from registry for prompt injection"
```

---

## Task 7: REST API + dependency

**Files:**
- Create: `atria/web/dependencies/modules.py`
- Create: `atria/web/routes/modules.py`
- Create: `tests/test_modules_routes.py`
- Modify: `atria/web/server.py` (register new router)
- Modify: `atria/web/dependencies/__init__.py` (export `get_modules_registry`)

- [ ] **Step 1: Write `atria/web/dependencies/modules.py`**

```python
"""FastAPI dependency: return the process-wide module registry."""
from __future__ import annotations

from atria.core.modules.registry import ModuleRegistry, get_registry


def get_modules_registry() -> ModuleRegistry:
    return get_registry()
```

- [ ] **Step 2: Re-export from `atria/web/dependencies/__init__.py`**

Add to the existing re-export block in `atria/web/dependencies/__init__.py`:

```python
from atria.web.dependencies.modules import get_modules_registry  # noqa: F401
```

- [ ] **Step 3: Write `atria/web/routes/modules.py`**

```python
"""REST API for file-based modules.

Endpoints (all rooted at ``/api/modules``):
- ``GET    /``               list modules
- ``GET    /{name}``         read one module
- ``POST   /``               create module (optional starter content overrides)
- ``PUT    /{name}``         overwrite SKILL.md + script.py
- ``DELETE /{name}``         delete module folder
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from atria.core.modules import store
from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import (
    InvalidModuleName,
    ModuleExists,
    ModuleNotFound,
)
from atria.web.dependencies import get_modules_registry


router = APIRouter(prefix="/api/modules", tags=["modules"])


class ModuleOut(BaseModel):
    name: str
    skill_md: str
    script_py: str
    mtime: float


class ModuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    skill_md: Optional[str] = None
    script_py: Optional[str] = None


class ModuleUpdate(BaseModel):
    skill_md: str
    script_py: str


def _to_out(m) -> ModuleOut:
    return ModuleOut(name=m.name, skill_md=m.skill_md, script_py=m.script_py, mtime=m.mtime)


@router.get("", response_model=List[ModuleOut])
def list_endpoint(reg: ModuleRegistry = Depends(get_modules_registry)):
    return [_to_out(m) for m in reg.all()]


@router.get("/{name}", response_model=ModuleOut)
def get_endpoint(name: str, reg: ModuleRegistry = Depends(get_modules_registry)):
    try:
        return _to_out(store.read_module(reg.root, name))
    except ModuleNotFound:
        raise HTTPException(404, f"module {name!r} not found")
    except InvalidModuleName as e:
        raise HTTPException(400, str(e))


@router.post("", response_model=ModuleOut, status_code=201)
def create_endpoint(body: ModuleCreate, reg: ModuleRegistry = Depends(get_modules_registry)):
    try:
        m = store.create_module(reg.root, body.name, skill_md=body.skill_md, script_py=body.script_py)
    except InvalidModuleName as e:
        raise HTTPException(400, str(e))
    except ModuleExists:
        raise HTTPException(409, f"module {body.name!r} already exists")
    reg.reload_one(body.name)
    return _to_out(m)


@router.put("/{name}", response_model=ModuleOut)
def update_endpoint(
    name: str, body: ModuleUpdate, reg: ModuleRegistry = Depends(get_modules_registry)
):
    try:
        m = store.update_module(reg.root, name, skill_md=body.skill_md, script_py=body.script_py)
    except InvalidModuleName as e:
        raise HTTPException(400, str(e))
    except ModuleNotFound:
        raise HTTPException(404, f"module {name!r} not found")
    reg.reload_one(name)
    return _to_out(m)


@router.delete("/{name}", status_code=204)
def delete_endpoint(name: str, reg: ModuleRegistry = Depends(get_modules_registry)):
    try:
        store.delete_module(reg.root, name)
    except InvalidModuleName as e:
        raise HTTPException(400, str(e))
    except ModuleNotFound:
        raise HTTPException(404, f"module {name!r} not found")
    reg.remove(name)
    return None
```

- [ ] **Step 4: Register the router in `atria/web/server.py`**

In `atria/web/server.py` after the other `app.include_router(...)` lines (around line 142), add:

```python
from atria.web.routes.modules import router as modules_router
app.include_router(modules_router)
```

Place the `import` with the other route imports near the top of the function/module, and the `include_router` call alongside the others.

- [ ] **Step 5: Write `tests/test_modules_routes.py`**

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.modules.registry import ModuleRegistry
from atria.web.dependencies import get_modules_registry
from atria.web.routes.modules import router as modules_router


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(modules_router)
    reg = ModuleRegistry(tmp_path / "modules")
    reg.load_all()
    app.dependency_overrides[get_modules_registry] = lambda: reg
    return TestClient(app)


def test_list_empty(client: TestClient):
    r = client.get("/api/modules")
    assert r.status_code == 200
    assert r.json() == []


def test_create_then_list_then_get(client: TestClient):
    r = client.post("/api/modules", json={"name": "demo"})
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "demo"
    r = client.get("/api/modules")
    assert [m["name"] for m in r.json()] == ["demo"]
    r = client.get("/api/modules/demo")
    assert r.status_code == 200
    assert "# demo" in r.json()["skill_md"]


def test_create_duplicate_returns_409(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.post("/api/modules", json={"name": "demo"})
    assert r.status_code == 409


def test_create_invalid_name_returns_400(client: TestClient):
    r = client.post("/api/modules", json={"name": "Bad Name"})
    assert r.status_code == 400


def test_update_overwrites_both_files(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.put(
        "/api/modules/demo",
        json={"skill_md": "# new", "script_py": "print('hi')\n"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["skill_md"] == "# new"
    assert body["script_py"] == "print('hi')\n"


def test_update_missing_returns_404(client: TestClient):
    r = client.put("/api/modules/nope", json={"skill_md": "x", "script_py": "y"})
    assert r.status_code == 404


def test_delete_removes_and_subsequent_get_404s(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.delete("/api/modules/demo")
    assert r.status_code == 204
    r = client.get("/api/modules/demo")
    assert r.status_code == 404
```

- [ ] **Step 6: Commit**

```bash
git add atria/web/dependencies/modules.py atria/web/dependencies/__init__.py atria/web/routes/modules.py atria/web/server.py tests/test_modules_routes.py
git commit -m "feat(modules): REST API for file-based modules (CRUD)"
```

---

## Task 8: Wire SKILL block into the agent prompt

**Files:**
- Modify: `atria/web/agent_executor.py`

- [ ] **Step 1: Add the new block injection in `atria/web/agent_executor.py`**

After the existing `## Workspace` append (around line 451 in the current file — the part starting `wd_str = str(working_dir)`), and before the `if not message_history or message_history[0].get("role") != "system":` block, insert:

```python
# Inject the file-based module SKILL block into the cached prefix so the LLM
# provider's prefix cache picks it up. Stable across turns; rebuilt only when
# the registry version bumps (i.e. when files change on disk).
try:
    from atria.core.modules.prompt import build_skill_block
    from atria.core.modules.registry import get_registry as _get_module_registry

    _modules_block = build_skill_block(_get_module_registry())
except Exception as _mod_err:  # never let modules break a chat turn
    logger.warning("Failed to build module SKILL block: %s", _mod_err)
    _modules_block = ""

if _modules_block:
    skill_block = "\n\n" + _modules_block
    system_content += skill_block
    if hasattr(agent, "_system_stable") and agent._system_stable:
        agent._system_stable += skill_block
```

Verify that no stale references to `_module_skill_md`, `_active_module_id`, or `get_module_loader` remain in this file.

- [ ] **Step 2: Commit**

```bash
git add atria/web/agent_executor.py
git commit -m "feat(modules): inject file-based SKILL block into agent system prompt"
```

---

## Task 9: Filesystem watcher + WebSocket broadcast

**Files:**
- Create: `atria/core/modules/watcher.py`
- Create: `tests/test_modules_watcher.py`
- Modify: `atria/web/server.py` (start watcher in lifespan)

- [ ] **Step 1: Write `tests/test_modules_watcher.py`**

```python
from __future__ import annotations

import time
from pathlib import Path

import pytest

from atria.core.modules import store
from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.watcher import ModuleWatcher


@pytest.fixture()
def reg(tmp_path: Path) -> ModuleRegistry:
    root = tmp_path / "modules"
    r = ModuleRegistry(root)
    r.load_all()
    return r


def _wait_for(predicate, timeout: float = 3.0, interval: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_create_then_modify_then_delete_triggers_callbacks(reg: ModuleRegistry):
    events = []
    w = ModuleWatcher(reg, on_change=lambda name: events.append(name))
    w.start()
    try:
        store.create_module(reg.root, "alpha")
        assert _wait_for(lambda: "alpha" in reg.names()), reg.names()
        store.update_module(reg.root, "alpha", skill_md="# changed", script_py="x\n")
        assert _wait_for(lambda: reg.get("alpha").skill_md == "# changed")
        store.delete_module(reg.root, "alpha")
        assert _wait_for(lambda: "alpha" not in reg.names())
        assert "alpha" in events
    finally:
        w.stop()


def test_irrelevant_files_are_ignored(reg: ModuleRegistry):
    events = []
    w = ModuleWatcher(reg, on_change=lambda name: events.append(name))
    w.start()
    try:
        # Make the folder so the watcher has a path to observe events in.
        store.create_module(reg.root, "demo")
        events.clear()
        # Touch an unrelated file.
        (reg.root / "demo" / "notes.txt").write_text("nope")
        # Brief settle period to ensure no spurious callback fires.
        time.sleep(0.5)
        assert events == []
    finally:
        w.stop()
```

- [ ] **Step 2: Implement `atria/core/modules/watcher.py`**

```python
"""Watchdog-based observer for ``~/.atria/modules``.

On any create/modify/delete of ``SKILL.md`` or ``script.py`` under a module
folder, reloads that module in the registry and invokes ``on_change(name)``.
Events are debounced per module name (200 ms) to coalesce editor-save bursts.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Dict, Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import SCRIPT_FILE, SKILL_FILE

logger = logging.getLogger(__name__)

DEBOUNCE_SEC = 0.2


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "ModuleWatcher") -> None:
        self._w = watcher

    def _module_name_for(self, raw_path: str) -> Optional[str]:
        try:
            p = Path(raw_path).resolve()
            rel = p.relative_to(self._w.registry.root.resolve())
        except (ValueError, OSError):
            return None
        parts = rel.parts
        if len(parts) < 2:
            return None
        if parts[-1] not in (SKILL_FILE, SCRIPT_FILE):
            return None
        return parts[0]

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            # A deleted folder fires per-file delete events for its children, which we
            # already pick up via _module_name_for. Folder events themselves are noisy.
            return
        name = self._module_name_for(event.src_path)
        if name:
            self._w.schedule(name)


class ModuleWatcher:
    """Filesystem observer that keeps a ``ModuleRegistry`` in sync."""

    def __init__(self, registry: ModuleRegistry, on_change: Callable[[str], None] | None = None):
        self.registry = registry
        self._on_change = on_change
        self._observer: Optional[Observer] = None
        self._timers: Dict[str, threading.Timer] = {}
        self._timers_lock = threading.Lock()

    def start(self) -> None:
        self.registry.root.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(self.registry.root), recursive=True)
        self._observer.start()
        logger.info("module watcher started on %s", self.registry.root)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None
        with self._timers_lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()

    def schedule(self, name: str) -> None:
        """Debounced reload-and-notify for ``name``."""
        with self._timers_lock:
            existing = self._timers.get(name)
            if existing is not None:
                existing.cancel()
            t = threading.Timer(DEBOUNCE_SEC, self._fire, args=(name,))
            t.daemon = True
            self._timers[name] = t
            t.start()

    def _fire(self, name: str) -> None:
        try:
            self.registry.reload_one(name)
        except Exception as e:  # never let watcher crash the server
            logger.warning("module reload failed for %s: %s", name, e)
            return
        if self._on_change is not None:
            try:
                self._on_change(name)
            except Exception as e:
                logger.warning("module on_change callback failed for %s: %s", name, e)


_WATCHER: Optional[ModuleWatcher] = None


def start_global_watcher(on_change: Callable[[str], None] | None = None) -> ModuleWatcher:
    """Start the process-wide watcher (idempotent)."""
    global _WATCHER
    if _WATCHER is not None:
        return _WATCHER
    from atria.core.modules.registry import get_registry

    _WATCHER = ModuleWatcher(get_registry(), on_change=on_change)
    _WATCHER.start()
    return _WATCHER


def stop_global_watcher() -> None:
    global _WATCHER
    if _WATCHER is not None:
        _WATCHER.stop()
        _WATCHER = None
```

- [ ] **Step 3: Start the watcher in `atria/web/server.py` lifespan**

Find the FastAPI lifespan function in `atria/web/server.py` (look for `@asynccontextmanager` or `lifespan=`). In the startup section (after the app is otherwise initialized), add:

```python
from atria.core.modules.watcher import start_global_watcher, stop_global_watcher
from atria.web.websocket import ws_manager  # import path may differ; use whatever the file already uses

def _broadcast_modules_changed(name: str) -> None:
    import asyncio, contextlib
    coro = ws_manager.broadcast({"type": "modules.changed", "name": name})
    with contextlib.suppress(RuntimeError):
        asyncio.get_event_loop().create_task(coro)

start_global_watcher(on_change=_broadcast_modules_changed)
```

In the shutdown section, add:

```python
stop_global_watcher()
```

If the file does not have a lifespan handler, wrap the existing `create_app()` (or equivalent) startup logic with `@app.on_event("startup")` and `@app.on_event("shutdown")` for the calls above. Use whichever pattern the file already uses; do not introduce a new style.

- [ ] **Step 4: Commit**

```bash
git add atria/core/modules/watcher.py tests/test_modules_watcher.py atria/web/server.py
git commit -m "feat(modules): watchdog observer + WS broadcast on module changes"
```

---

## Task 10: Frontend — delete old UI, add Artifact Viewer integration

**Files:**
- Delete: `web-ui/src/pages/modules/` (entire folder)
- Delete: `web-ui/src/components/ModulePicker.tsx`
- Modify: `web-ui/src/App.tsx`
- Modify: `web-ui/src/components/Layout/TopBar.tsx`
- Create: `web-ui/src/api/modules.ts`
- Create: `web-ui/src/stores/modules.ts`
- Create: `web-ui/src/components/ArtifactViewer/LeftPaneTabs.tsx`
- Create: `web-ui/src/components/ArtifactViewer/ModuleList.tsx`
- Create: `web-ui/src/components/ArtifactViewer/viewers/ModuleEditor.tsx`
- Modify: `web-ui/src/components/ArtifactViewer/ArtifactViewer.tsx`
- Modify: `web-ui/src/components/ArtifactViewer/viewers/index.tsx`
- Modify: `web-ui/src/stores/viewerTabs.ts`
- Modify: `web-ui/src/types/index.ts`
- Modify: `web-ui/src/stores/chat.ts`

- [ ] **Step 1: Delete the old modules UI surface**

```bash
rm -rf web-ui/src/pages/modules
rm -f web-ui/src/components/ModulePicker.tsx
```

- [ ] **Step 2: Strip module routes from `web-ui/src/App.tsx`**

In `web-ui/src/App.tsx`, delete:
- the three `lazy(() => import('./pages/modules/...'))` lines (`ModulesListPage`, `ModuleDetailPage`, `TaskEditorPage`),
- the four `<Route path="/modules*" ...>` entries.

Save and confirm no references to `ModulesListPage` / `ModuleDetailPage` / `TaskEditorPage` remain.

- [ ] **Step 3: Remove the Modules link from `TopBar.tsx`**

In `web-ui/src/components/Layout/TopBar.tsx`, delete the `<Link to="/modules" ...>Modules</Link>` block (around line 111). Remove any icon import that becomes unused.

- [ ] **Step 4: Also remove `ModulePicker` usage from the chat header**

Search the project for `ModulePicker` and remove every import + JSX usage:

```bash
grep -rln "ModulePicker" web-ui/src
```

Delete the matching import lines and the `<ModulePicker ... />` element from any chat-header component. (Per the spec, modules are no longer per-conversation selectable.)

- [ ] **Step 5: Create `web-ui/src/api/modules.ts`**

```typescript
import { apiClient } from './apiClient'; // use whichever shared client your repo uses; fall back to fetch if none

export interface Module {
  name: string;
  skill_md: string;
  script_py: string;
  mtime: number;
}

const BASE = '/api/modules';

export const ModulesApi = {
  async list(): Promise<Module[]> {
    const r = await fetch(BASE);
    if (!r.ok) throw new Error(`list modules: ${r.status}`);
    return r.json();
  },
  async get(name: string): Promise<Module> {
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}`);
    if (!r.ok) throw new Error(`get module: ${r.status}`);
    return r.json();
  },
  async create(name: string): Promise<Module> {
    const r = await fetch(BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) throw new Error(`create module: ${r.status}`);
    return r.json();
  },
  async update(name: string, skill_md: string, script_py: string): Promise<Module> {
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_md, script_py }),
    });
    if (!r.ok) throw new Error(`update module: ${r.status}`);
    return r.json();
  },
  async remove(name: string): Promise<void> {
    const r = await fetch(`${BASE}/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!r.ok && r.status !== 204) throw new Error(`delete module: ${r.status}`);
  },
};
```

If the project has a shared `apiClient` helper with auth headers, swap the bare `fetch` calls for it. (Check `web-ui/src/api/` for the existing convention before settling on which call style to use.)

- [ ] **Step 6: Create `web-ui/src/stores/modules.ts`**

```typescript
import { create } from 'zustand';
import { ModulesApi, type Module } from '../api/modules';

interface State {
  modules: Module[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (name: string) => Promise<Module>;
  save: (name: string, skill_md: string, script_py: string) => Promise<Module>;
  remove: (name: string) => Promise<void>;
}

export const useModulesStore = create<State>((set, get) => ({
  modules: [],
  loading: false,
  error: null,
  async refresh() {
    set({ loading: true, error: null });
    try {
      const modules = await ModulesApi.list();
      set({ modules, loading: false });
    } catch (e: any) {
      set({ error: String(e), loading: false });
    }
  },
  async create(name) {
    const m = await ModulesApi.create(name);
    await get().refresh();
    return m;
  },
  async save(name, skill_md, script_py) {
    const m = await ModulesApi.update(name, skill_md, script_py);
    await get().refresh();
    return m;
  },
  async remove(name) {
    await ModulesApi.remove(name);
    await get().refresh();
  },
}));
```

- [ ] **Step 7: Hook the WS event into the modules store**

Open `web-ui/src/stores/chat.ts` (the file that owns the WS event dispatcher; if it lives elsewhere, follow the existing dispatcher pattern). In the switch/handler that processes incoming WS messages, add a case:

```typescript
case 'modules.changed': {
  // Lazy import to avoid a cycle with stores/modules.ts.
  import('./modules').then(({ useModulesStore }) => useModulesStore.getState().refresh());
  break;
}
```

If the dispatcher is structured as an `if (msg.type === 'X')` chain, mirror that style instead.

- [ ] **Step 8: Extend `ViewerTab` to support `kind: 'module'`**

In `web-ui/src/types/index.ts`, locate the `ViewerTab` interface. Change it to a discriminated union (or add the new fields, whichever fits the existing style):

```typescript
export type ViewerTab =
  | {
      kind: 'file';
      id: string;
      path: string;
      name: string;
      ext: string;
    }
  | {
      kind: 'module';
      id: string;        // use `module:<name>`
      name: string;      // module name
    };
```

If existing call sites assume `path`/`ext` always exist, add narrowing checks (`if (tab.kind === 'file')`) where the TypeScript compiler complains.

- [ ] **Step 9: Update `web-ui/src/stores/viewerTabs.ts`**

Open `web-ui/src/stores/viewerTabs.ts`. Update the helper `tabFromPath` (around line 17) and any `add()` function so they construct the new discriminated `ViewerTab` shape. Add a sibling helper:

```typescript
function tabFromModule(name: string): ViewerTab {
  return { kind: 'module', id: `module:${name}`, name };
}

export function openModuleTab(state: ViewerTabsState, convId: string, name: string) {
  // Implementation should follow the existing openTab/add pattern.
}
```

Export `openModuleTab` and make sure the open/close/select reducers handle module tabs the same way they handle file tabs (lookup by `id`).

- [ ] **Step 10: Update the viewer dispatcher**

In `web-ui/src/components/ArtifactViewer/viewers/index.tsx`, the current `ViewerDispatcher` assumes `path/ext`. Change it to switch on `tab.kind` first:

```typescript
import { ModuleEditor } from './ModuleEditor';

export function ViewerDispatcher({ convId, tab }: { convId: string; tab: ViewerTab }) {
  if (tab.kind === 'module') {
    return <ModuleEditor name={tab.name} />;
  }
  // existing file-mode logic unchanged, using tab.path / tab.name / tab.ext
}
```

Update the caller in `ArtifactViewer.tsx` accordingly (pass the full `tab` object instead of separate `path/name/ext` props).

- [ ] **Step 11: Create `web-ui/src/components/ArtifactViewer/LeftPaneTabs.tsx`**

```tsx
import React from 'react';
import { useLocalStorage } from 'usehooks-ts';

export type LeftMode = 'files' | 'modules';

interface Props {
  mode: LeftMode;
  onChange: (m: LeftMode) => void;
}

export function LeftPaneTabs({ mode, onChange }: Props) {
  const btn = (m: LeftMode, label: string) => (
    <button
      key={m}
      onClick={() => onChange(m)}
      className={[
        'px-2 py-1 text-xs rounded transition-colors cursor-pointer',
        mode === m
          ? 'bg-surface-soft text-ink'
          : 'text-ink/55 hover:text-ink hover:bg-surface-soft/60',
      ].join(' ')}
    >
      {label}
    </button>
  );
  return (
    <div className="flex items-center gap-1 px-2 py-1 border-b border-hairline-soft/60">
      {btn('files', 'Files')}
      {btn('modules', 'Modules')}
    </div>
  );
}

export function useLeftMode() {
  return useLocalStorage<LeftMode>('artifact-viewer.left-mode', 'files');
}
```

- [ ] **Step 12: Create `web-ui/src/components/ArtifactViewer/ModuleList.tsx`**

```tsx
import React, { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useModulesStore } from '../../stores/modules';
import { useViewerTabsStore } from '../../stores/viewerTabs';

interface Props {
  convId: string;
}

function firstSummaryLine(skill_md: string): string {
  for (const raw of skill_md.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith('#')) continue;
    return line.length > 80 ? line.slice(0, 77) + '…' : line;
  }
  return '';
}

export function ModuleList({ convId }: Props) {
  const { modules, loading, error, refresh, create, remove } = useModulesStore();
  const openModule = useViewerTabsStore(s => (s as any).openModuleTab);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const onCreate = async () => {
    const name = window.prompt('Module name (lowercase, digits, _ or -)');
    if (!name) return;
    setBusy(true);
    try {
      const m = await create(name);
      openModule(convId, m.name);
    } catch (e: any) {
      window.alert(`Failed: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (name: string) => {
    if (!window.confirm(`Delete module "${name}"? This removes the folder.`)) return;
    await remove(name);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between px-2 py-1 border-b border-hairline-soft/60">
        <span className="text-[11px] uppercase tracking-wide text-ink/50">Modules</span>
        <button
          onClick={onCreate}
          disabled={busy}
          aria-label="New module"
          className="p-1 rounded text-ink/55 hover:text-ink hover:bg-surface-soft cursor-pointer transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto text-xs">
        {loading && modules.length === 0 && <div className="px-2 py-2 text-ink/40">Loading…</div>}
        {error && <div className="px-2 py-2 text-rose-500">{error}</div>}
        {modules.length === 0 && !loading && (
          <div className="px-2 py-3 text-ink/40">No modules. Click + to create one.</div>
        )}
        {modules.map(m => (
          <div
            key={m.name}
            className="group flex items-center justify-between px-2 py-1.5 hover:bg-surface-soft/70 cursor-pointer"
            onClick={() => openModule(convId, m.name)}
          >
            <div className="min-w-0">
              <div className="font-medium truncate">{m.name}</div>
              <div className="text-ink/45 truncate">{firstSummaryLine(m.skill_md)}</div>
            </div>
            <button
              onClick={e => { e.stopPropagation(); onDelete(m.name); }}
              aria-label={`Delete ${m.name}`}
              className="opacity-0 group-hover:opacity-100 p-1 rounded text-ink/45 hover:text-rose-500 hover:bg-surface-soft cursor-pointer transition"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 13: Create `web-ui/src/components/ArtifactViewer/viewers/ModuleEditor.tsx`**

The project already uses CodeMirror via `@uiw/react-codemirror` for some viewers — confirm the actual package in `web-ui/package.json` and substitute if different. The MonacoViewer pattern in the same `viewers/` folder is a working reference; if Monaco is the prevailing editor, mirror that import instead.

```tsx
import React, { useEffect, useState } from 'react';
import { Save, Loader2 } from 'lucide-react';
import CodeMirror from '@uiw/react-codemirror';
import { markdown } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import { useModulesStore } from '../../../stores/modules';

interface Props {
  name: string;
}

export function ModuleEditor({ name }: Props) {
  const { modules, save, refresh } = useModulesStore();
  const found = modules.find(m => m.name === name);

  const [skill, setSkill] = useState(found?.skill_md ?? '');
  const [script, setScript] = useState(found?.script_py ?? '');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (found && !dirty) {
      setSkill(found.skill_md);
      setScript(found.script_py);
    }
    if (!found) refresh();
  }, [found, dirty, refresh]);

  const onSave = async () => {
    setSaving(true);
    try {
      await save(name, skill, script);
      setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  if (!found) {
    return <div className="p-4 text-ink/50 text-sm">Loading module {name}…</div>;
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-hairline-soft/60 flex-shrink-0">
        <span className="font-medium">{name}</span>
        {dirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-500" title="Unsaved changes" />}
        <div className="flex-1" />
        <button
          onClick={onSave}
          disabled={!dirty || saving}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-sky-500/90 text-white hover:bg-sky-500 disabled:opacity-40 cursor-pointer transition-colors"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          Save
        </button>
      </div>
      <div className="flex flex-col flex-1 min-h-0">
        <div className="flex-1 overflow-auto border-b border-hairline-soft/60 min-h-[20%]">
          <div className="px-3 py-1 text-[11px] uppercase tracking-wide text-ink/50">SKILL.md</div>
          <CodeMirror
            value={skill}
            height="100%"
            extensions={[markdown()]}
            onChange={v => { setSkill(v); setDirty(true); }}
          />
        </div>
        <div className="flex-1 overflow-auto min-h-[20%]">
          <div className="px-3 py-1 text-[11px] uppercase tracking-wide text-ink/50">script.py</div>
          <CodeMirror
            value={script}
            height="100%"
            extensions={[python()]}
            onChange={v => { setScript(v); setDirty(true); }}
          />
        </div>
      </div>
    </div>
  );
}
```

If `@uiw/react-codemirror`, `@codemirror/lang-markdown`, or `@codemirror/lang-python` are not already in `web-ui/package.json`, install them:

```bash
cd web-ui && npm install @uiw/react-codemirror @codemirror/lang-markdown @codemirror/lang-python
```

(Check `package.json` first — only install what is missing.)

- [ ] **Step 14: Wire `LeftPaneTabs` + `ModuleList` into `ArtifactViewer.tsx`**

In `web-ui/src/components/ArtifactViewer/ArtifactViewer.tsx`, around the `<FileTree convId={...} />` block (currently line ~115), replace it with:

```tsx
import { LeftPaneTabs, useLeftMode } from './LeftPaneTabs';
import { ModuleList } from './ModuleList';

// inside the component body:
const [leftMode, setLeftMode] = useLeftMode();

// inside the left pane container:
<div className="flex flex-col h-full">
  <LeftPaneTabs mode={leftMode} onChange={setLeftMode} />
  <div className="flex-1 overflow-hidden">
    {leftMode === 'files'
      ? <FileTree convId={currentSessionId} />
      : <ModuleList convId={currentSessionId} />}
  </div>
</div>
```

Then update the `<ViewerDispatcher .../>` call site to use the new `tab`-prop signature (introduced in Step 10). Pseudocode for the right pane:

```tsx
{activeTab ? <ViewerDispatcher convId={currentSessionId} tab={activeTab} /> : null}
```

- [ ] **Step 15: Build the frontend**

```bash
make build-ui
```

Expected: clean build, no TypeScript errors, output bundle written to `atria/web/static/`.

- [ ] **Step 16: Commit**

```bash
git add web-ui/src web-ui/package.json web-ui/package-lock.json atria/web/static
git commit -m "feat(modules): file-based modules UI in Artifact Viewer; remove legacy /modules pages"
```

---

## Task 11: Verification pass — run the full suite and exercise end-to-end

**Files:** none (verification only)

- [ ] **Step 1: Run formatting + lint + typecheck**

```bash
make check
```

Expected: zero errors. Fix anything reported before continuing.

- [ ] **Step 2: Run the full test suite**

```bash
make test
```

Expected: all tests pass. The new tests added in Tasks 4–7 and 9 should appear in the run.

- [ ] **Step 3: End-to-end (per CLAUDE.md: MUST run real API)**

Ensure `OPENAI_API_KEY` is set:

```bash
echo "${OPENAI_API_KEY:0:6}…"  # confirm it is set
```

Start the web UI:

```bash
make run
```

In a separate terminal:

1. Create a module by calling the API directly to confirm wiring:

```bash
curl -sS -XPOST http://localhost:8000/api/modules \
  -H 'Content-Type: application/json' \
  -d '{"name":"echo_demo"}' | jq
```

Expected: 201 with starter SKILL.md / script.py.

2. Edit the script on disk to make it do something observable, e.g.:

```bash
cat > ~/.atria/modules/echo_demo/script.py <<'PY'
import sys, json
print(json.dumps({"echoed": sys.argv[1:]}))
PY
```

Then update `SKILL.md` via the API so the agent knows about it:

```bash
curl -sS -XPUT http://localhost:8000/api/modules/echo_demo \
  -H 'Content-Type: application/json' \
  -d '{"skill_md":"# echo_demo\n\nPrints its argv as JSON. Run: `python ~/.atria/modules/echo_demo/script.py hello`","script_py":"import sys, json\nprint(json.dumps({\"echoed\": sys.argv[1:]}))\n"}' | jq
```

3. Open the web UI, switch the left pane to **Modules**, confirm `echo_demo` appears, click it, confirm the two-pane editor shows the new content.

4. In a chat session, send: *"Use the echo_demo module to echo the word 'hello'. Show the raw output."* — confirm the agent calls bash with `python ~/.atria/modules/echo_demo/script.py hello` and reports `{"echoed": ["hello"]}`.

5. Touch a file externally to verify the watcher: `touch ~/.atria/modules/echo_demo/SKILL.md`. Confirm the UI list re-renders (because of the `modules.changed` WS event) without a manual refresh.

6. Confirm legacy state is gone:

```bash
sqlite3 ~/.atria/atria.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'module%';"
```

Expected: empty output (legacy `modules`, `module_tools`, `module_tasks` dropped).

- [ ] **Step 4: Commit anything the verification surfaced**

If formatter or build artifacts changed:

```bash
git add -A
git commit -m "chore(modules): post-verification cleanup"
```

(If there is nothing to commit, skip this step.)

---

## Self-Review (filled in)

**1. Spec coverage:** every spec section maps to a task — store/registry/watcher/prompt (Tasks 4–6, 9), HTTP API (Task 7), prompt injection (Task 8), UI removal (Task 10 steps 1–4), Artifact Viewer integration (Task 10 steps 11–14), autoload + WS (Tasks 7 step 4 + 9 + 10 step 7), migration drop (Task 3), test plan (Tasks 4–7, 9, 11), watchdog dep (Task 1).

**2. Placeholder scan:** no `TBD` / `TODO` / "implement later" / "similar to Task N" / "add appropriate error handling" remain. Every step that touches code includes the exact code.

**3. Type consistency:** `Module` dataclass fields (`name`, `skill_md`, `script_py`, `dir`, `mtime`) are used identically in store, registry, prompt, routes, and the React `Module` interface. `ModuleRegistry` methods (`load_all`, `reload_one`, `remove`, `all`, `names`, `get`, `version`, `root`) are called the same way everywhere. WS event shape `{type: "modules.changed", name}` is identical in producer (`agent_executor`-side `_broadcast_modules_changed`) and consumer (`stores/chat.ts`). REST routes (`GET/POST/PUT/DELETE /api/modules[/{name}]`) match between `routes/modules.py`, `api/modules.ts`, and the curl checks in Task 11.
