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


def _make_module_with_subskills(root: Path, name: str) -> Path:
    """Create a module on disk with frontmatter + one sub-skill under skills/."""
    d = root / name
    (d / "skills").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Frontmatter desc for {name}.\n---\n\n"
        f"# {name}\n\n## When to use\n- triggers for {name}\n\n## How to use\nDETAIL_BODY\n",
        encoding="utf-8",
    )
    (d / "skills" / "reporting.md").write_text(
        "---\nname: reporting\ndescription: Reports and KPIs.\n---\n\n# reporting\n\nSUBSKILL_BODY\n",
        encoding="utf-8",
    )
    return d


def test_empty_registry_returns_empty_string(tmp_path: Path):
    r = ModuleRegistry(tmp_path / "empty")
    r.load_all()
    assert build_skill_block(r) == ""


def test_catalog_has_header_and_modules_sorted(reg: ModuleRegistry):
    out = build_skill_block(reg)
    assert "## Active Modules" in out
    assert out.index("### alpha") < out.index("### bravo")
    assert "Does alpha things." in out
    assert "Does bravo things." in out


def test_catalog_is_lazy_not_full_body(reg: ModuleRegistry):
    out = build_skill_block(reg)
    # The 'When to use' triggers ARE inlined so the agent can decide to load...
    assert "describe trigger conditions" in out
    # ...but the rest of the body (How to use) is NOT — it loads on demand.
    assert "Run scripts via the bash tool" not in out
    assert 'invoke_skill("alpha")' in out


def test_catalog_lists_files_for_dashboard_module(reg: ModuleRegistry):
    out = build_skill_block(reg)
    assert "Files:" in out
    assert "scripts/main.py" in out
    assert "templates/dashboard.html" in out


def test_frontmatter_description_and_subskill_discovery(tmp_path: Path):
    root = tmp_path / "modules"
    _make_module_with_subskills(root, "charlie")
    r = ModuleRegistry(root)
    r.load_all()

    m = r.get("charlie")
    assert m.description == "Frontmatter desc for charlie."
    assert [s.name for s in m.subskills] == ["reporting"]
    assert m.subskills[0].description == "Reports and KPIs."

    out = build_skill_block(r)
    assert "Frontmatter desc for charlie." in out
    assert 'invoke_skill("charlie:reporting")' in out
    assert "Reports and KPIs." in out
    # Neither the module body nor the sub-skill body is inlined.
    assert "DETAIL_BODY" not in out
    assert "SUBSKILL_BODY" not in out


def test_invoke_skill_resolves_module_and_subskill(tmp_path: Path, monkeypatch):
    import atria.core.modules.registry as reg_mod
    from atria.core.skills import SkillLoader

    root = tmp_path / "modules"
    _make_module_with_subskills(root, "delta")
    r = ModuleRegistry(root)
    r.load_all()
    monkeypatch.setattr(reg_mod, "get_registry", lambda: r)

    loader = SkillLoader([])  # no .atria/skills dirs — modules only
    names = loader.get_skill_names()
    assert "delta" in names
    assert "delta:reporting" in names

    loaded = loader.load_skill("delta:reporting")
    assert loaded is not None
    assert "SUBSKILL_BODY" in loaded.content
    assert "description:" not in loaded.content  # frontmatter stripped

    # Modules are catalogued under "Active Modules", not the skills index.
    assert loader.build_skills_index() == ""
