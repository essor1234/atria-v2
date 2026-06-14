from pathlib import Path

import pytest

from atria.core.skill_tools import (
    SkillToolContext,
    SkillToolError,
    SkillToolLoader,
)


def _write_skill(skill_dir: Path, name: str, tools_py: str, *, declare_tools: bool = True) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    tools_line = "tools: tools.py\n" if declare_tools else ""
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n{tools_line}---\n\nBody.\n",
        encoding="utf-8",
    )
    (skill_dir / "tools.py").write_text(tools_py, encoding="utf-8")


def test_discovers_and_registers(tmp_path: Path):
    _write_skill(
        tmp_path / "alpha",
        "alpha",
        "from atria.core.skill_tools import ToolSpec\n"
        "def register(ctx):\n"
        "    return [ToolSpec(name='alpha_tool', description='d',\n"
        "                    parameters={'type':'object'},\n"
        "                    handler=lambda **k: {'success': True, 'output': 'alpha'})]\n",
    )
    loader = SkillToolLoader([tmp_path])
    specs = loader.discover_and_register(SkillToolContext())
    assert [s.name for s in specs] == ["alpha_tool"]
    assert specs[0].handler()["output"] == "alpha"


def test_skill_without_tools_declaration_ignored(tmp_path: Path):
    _write_skill(
        tmp_path / "beta",
        "beta",
        "def register(ctx):\n    raise AssertionError('should not be called')\n",
        declare_tools=False,
    )
    loader = SkillToolLoader([tmp_path])
    assert loader.discover_and_register(SkillToolContext()) == []


def test_duplicate_tool_name_raises(tmp_path: Path):
    body = (
        "from atria.core.skill_tools import ToolSpec\n"
        "def register(ctx):\n"
        "    return [ToolSpec(name='dup', description='d',\n"
        "                    parameters={}, handler=lambda **k: {})]\n"
    )
    _write_skill(tmp_path / "one", "one", body)
    _write_skill(tmp_path / "two", "two", body)
    loader = SkillToolLoader([tmp_path])
    with pytest.raises(SkillToolError, match="Duplicate tool name 'dup'"):
        loader.discover_and_register(SkillToolContext())


def test_missing_register_raises(tmp_path: Path):
    _write_skill(tmp_path / "no_reg", "no_reg", "# no register\n")
    loader = SkillToolLoader([tmp_path])
    with pytest.raises(SkillToolError, match="missing required `register"):
        loader.discover_and_register(SkillToolContext())


def test_register_must_return_list(tmp_path: Path):
    _write_skill(
        tmp_path / "bad",
        "bad",
        "def register(ctx):\n    return 'not a list'\n",
    )
    loader = SkillToolLoader([tmp_path])
    with pytest.raises(SkillToolError, match="must return list"):
        loader.discover_and_register(SkillToolContext())


def test_skill_can_use_sibling_module(tmp_path: Path):
    """Sibling modules in the skill folder should resolve via relative import."""
    skill = tmp_path / "with_sibling"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: with_sibling\ndescription: d\ntools: tools.py\n---\n",
        encoding="utf-8",
    )
    (skill / "helper.py").write_text("VALUE = 42\n", encoding="utf-8")
    (skill / "tools.py").write_text(
        "from atria.core.skill_tools import ToolSpec\n"
        "from .helper import VALUE\n"
        "def register(ctx):\n"
        "    return [ToolSpec(name='sib', description='d', parameters={},\n"
        "                    handler=lambda **k: {'value': VALUE})]\n",
        encoding="utf-8",
    )
    loader = SkillToolLoader([tmp_path])
    specs = loader.discover_and_register(SkillToolContext())
    assert specs[0].handler()["value"] == 42
