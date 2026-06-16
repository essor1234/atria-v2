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
        store.write_file(reg.root, "alpha", "SKILL.md", "# changed")
        assert _wait_for(lambda: reg.get("alpha").skill_md == "# changed")
        store.delete_module(reg.root, "alpha")
        assert _wait_for(lambda: "alpha" not in reg.names())
        # Notify is debounced ~500ms after the last fs event; wait for it to land.
        assert _wait_for(lambda: "alpha" in events)
    finally:
        w.stop()


def test_any_file_change_in_module_triggers_reload(reg: ModuleRegistry):
    events = []
    w = ModuleWatcher(reg, on_change=lambda name: events.append(name))
    w.start()
    try:
        store.create_module(reg.root, "demo")
        assert _wait_for(lambda: "demo" in events)
        events.clear()
        # A new file under scripts/ should trigger a reload.
        (reg.root / "demo" / "scripts").mkdir(exist_ok=True)
        (reg.root / "demo" / "scripts" / "foo.py").write_text("print('hi')\n")
        assert _wait_for(lambda: "scripts/foo.py" in reg.get("demo").files)
    finally:
        w.stop()


def test_pycache_and_tmp_files_are_ignored(reg: ModuleRegistry):
    events = []
    w = ModuleWatcher(reg, on_change=lambda name: events.append(name))
    w.start()
    try:
        store.create_module(reg.root, "demo")
        assert _wait_for(lambda: "demo" in events)
        events.clear()
        # Pycache + atomic-write temp files should not fire reload.
        (reg.root / "demo" / "__pycache__").mkdir(exist_ok=True)
        (reg.root / "demo" / "__pycache__" / "x.cpython-314.pyc").write_text("x")
        (reg.root / "demo" / ".tmp-SKILL.md").write_text("x")
        time.sleep(0.5)
        assert events == []
    finally:
        w.stop()
