import json
from pathlib import Path

from atria.core.modules.activity import resolve_activity_label
from atria.core.modules.store import ActivityLabel


def _make_module(root: Path) -> Path:
    mod = root / "warehouse"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "inventory.py").write_text("# script\n")
    (mod / "manifest.json").write_text(
        json.dumps(
            {
                "activity": {
                    "default": {"running": "Working in Warehouse…", "done": "Done"},
                    "actions": {
                        "receive": {"running": "Receiving stock…", "done": "Stock received"},
                    },
                }
            }
        )
    )
    return mod


def test_resolves_action_label(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py receive --sku SKU-001 --qty 50"
    assert resolve_activity_label(cmd, tmp_path) == ActivityLabel(
        running="Receiving stock…", done="Stock received"
    )


def test_falls_back_to_default_for_unknown_action(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py teleport"
    assert resolve_activity_label(cmd, tmp_path) == ActivityLabel(
        running="Working in Warehouse…", done="Done"
    )


def test_flags_skipped_when_finding_subcommand(tmp_path: Path):
    mod = _make_module(tmp_path)
    cmd = f"python {mod}/scripts/inventory.py --json receive"
    assert resolve_activity_label(cmd, tmp_path).running == "Receiving stock…"


def test_non_module_command_returns_none(tmp_path: Path):
    _make_module(tmp_path)
    assert resolve_activity_label("grep -r foo .", tmp_path) is None


def test_module_without_activity_returns_none(tmp_path: Path):
    mod = tmp_path / "bare"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "main.py").write_text("# s\n")
    (mod / "manifest.json").write_text(json.dumps({"display_name": "Bare"}))
    cmd = f"python {mod}/scripts/main.py run"
    assert resolve_activity_label(cmd, tmp_path) is None
