"""Tests for the filesystem-backed module store."""

from __future__ import annotations

from pathlib import Path

import pytest

from atria.core.modules.store import (
    MODULE_NAME_RE,
    InvalidModuleName,
    Module,
    ModuleExists,
    ModuleNotFound,
    create_module,
    delete_file,
    delete_module,
    list_dir,
    list_modules,
    read_file,
    read_module,
    write_file,
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "modules"


def test_name_regex_accepts_valid_and_rejects_invalid():
    assert MODULE_NAME_RE.fullmatch("my_module-1")
    assert not MODULE_NAME_RE.fullmatch("Bad Name")
    assert not MODULE_NAME_RE.fullmatch("../escape")


def test_create_skill_template(root: Path):
    m = create_module(root, "demo")
    assert isinstance(m, Module)
    assert m.name == "demo"
    assert "# demo" in m.skill_md
    assert "SKILL.md" in m.files
    assert (root / "demo" / "SKILL.md").is_file()


def test_create_skill_script_template_scaffolds_scripts_dir(root: Path):
    m = create_module(root, "demo", template="skill_script")
    assert (root / "demo" / "scripts" / "main.py").is_file()
    assert "scripts/main.py" in m.files


def test_create_skill_dashboard_template_scaffolds_templates_dir(root: Path):
    m = create_module(root, "demo", template="skill_dashboard")
    assert (root / "demo" / "templates" / "dashboard.html").is_file()
    assert "scripts/main.py" in m.files
    assert "templates/dashboard.html" in m.files


def test_create_blank_template(root: Path):
    m = create_module(root, "demo", template="blank")
    assert m.skill_md == ""
    assert m.files == ["SKILL.md"]


def test_create_rejects_invalid_name(root: Path):
    with pytest.raises(InvalidModuleName):
        create_module(root, "Bad Name")


def test_create_rejects_existing(root: Path):
    create_module(root, "demo")
    with pytest.raises(ModuleExists):
        create_module(root, "demo")


def test_write_then_read_file_in_scripts_dir(root: Path):
    create_module(root, "demo")
    write_file(root, "demo", "scripts/foo.py", "print('hi')\n")
    assert read_file(root, "demo", "scripts/foo.py") == b"print('hi')\n"
    m = read_module(root, "demo")
    assert "scripts/foo.py" in m.files


def test_write_rejects_path_traversal(root: Path):
    create_module(root, "demo")
    with pytest.raises(ValueError):
        write_file(root, "demo", "../escape.txt", "nope")


def test_delete_file_removes_it_but_protects_skill_md(root: Path):
    create_module(root, "demo", template="skill_script")
    delete_file(root, "demo", "scripts/main.py")
    assert not (root / "demo" / "scripts" / "main.py").exists()
    with pytest.raises(ValueError):
        delete_file(root, "demo", "SKILL.md")


def test_list_dir_root_and_subdir(root: Path):
    create_module(root, "demo", template="skill_dashboard")
    top = list_dir(root, "demo", "")
    names = sorted(e["name"] for e in top)
    assert names == ["SKILL.md", "manifest.json", "scripts", "templates"]
    sub = list_dir(root, "demo", "scripts")
    assert [e["name"] for e in sub] == ["main.py"]


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


def test_read_module_missing_raises(root: Path):
    with pytest.raises(ModuleNotFound):
        read_module(root, "nope")


# ── manifest.json ──────────────────────────────────────────────────────────


def test_manifest_scaffolded_for_skill_dashboard_template(root: Path):
    m = create_module(root, "shop", template="skill_dashboard")
    assert m.manifest is not None
    assert m.manifest.display_name == "Shop"
    assert m.manifest.icon == "icon.svg"
    assert m.manifest.dashboard is not None
    assert m.manifest.dashboard.default_height == 720
    assert m.manifest.dashboard.badge_color == "warning"


def test_manifest_not_scaffolded_for_blank_template(root: Path):
    m = create_module(root, "raw", template="blank")
    assert m.manifest is None
    assert not (root / "raw" / "manifest.json").exists()


def test_manifest_lenient_on_invalid_json(root: Path, caplog: pytest.LogCaptureFixture):
    create_module(root, "demo", template="skill")
    (root / "demo" / "manifest.json").write_text("{not valid json", encoding="utf-8")
    m = read_module(root, "demo")
    assert m.manifest is None  # falls back, module still loads


def test_manifest_ignores_unknown_keys_and_bad_badge(root: Path):
    create_module(root, "demo", template="skill")
    (root / "demo" / "manifest.json").write_text(
        '{"display_name": "Demo Box", "tooltip": "hover me", "icon": "icon.svg", '
        '"future_field": 42, "dashboard": {"title": "x", "default_height": 500, '
        '"badge_color": "neon-pink"}}',
        encoding="utf-8",
    )
    m = read_module(root, "demo")
    assert m.manifest is not None
    assert m.manifest.display_name == "Demo Box"
    assert m.manifest.tooltip == "hover me"
    assert m.manifest.dashboard is not None
    assert m.manifest.dashboard.default_height == 500
    assert m.manifest.dashboard.badge_color is None  # invalid value dropped


def test_parse_activity_default_and_actions():
    from atria.core.modules.store import _parse_activity, ActivityLabel

    default, actions = _parse_activity(
        {
            "default": {"running": "Working in Warehouse…", "done": "Done"},
            "actions": {
                "receive": {"running": "Receiving stock…", "done": "Stock received"},
            },
        }
    )
    assert default == ActivityLabel(running="Working in Warehouse…", done="Done")
    assert actions["receive"] == ActivityLabel(running="Receiving stock…", done="Stock received")


def test_parse_activity_missing_degrades_to_empty():
    from atria.core.modules.store import _parse_activity

    assert _parse_activity(None) == (None, {})
    assert _parse_activity("nonsense") == (None, {})
    assert _parse_activity({}) == (None, {})
