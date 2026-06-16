from __future__ import annotations

from pathlib import Path

import pytest

from atria.core.modules import store
from atria.core.modules.prompt import build_skill_block
from atria.core.modules.registry import ModuleRegistry


@pytest.fixture()
def reg(tmp_path: Path) -> ModuleRegistry:
    root = tmp_path / "modules"
    store.create_module(root, "alpha", template="skill", summary="Does alpha things.")
    store.create_module(root, "bravo", template="skill_dashboard", summary="Does bravo things.")
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
    assert "~/.atria/modules/<name>" in out
    # Module sections appear in sorted order
    assert out.index("### alpha") < out.index("### bravo")
    assert "Does alpha things." in out
    assert "Does bravo things." in out


def test_block_lists_module_files_for_dashboard_module(reg: ModuleRegistry):
    out = build_skill_block(reg)
    # bravo was scaffolded with scripts + templates
    assert "Files:" in out
    assert "scripts/main.py" in out
    assert "templates/dashboard.html" in out
