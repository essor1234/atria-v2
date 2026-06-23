import json
from pathlib import Path

from atria.web.ws_tool_broadcaster import WebSocketToolBroadcaster


def _broadcaster() -> WebSocketToolBroadcaster:
    # Build without wiring a real registry/ws/loop; we only call _activity_for.
    b = WebSocketToolBroadcaster.__new__(WebSocketToolBroadcaster)
    return b


def test_activity_for_bash_module_script(tmp_path: Path, monkeypatch):
    mod = tmp_path / "warehouse"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "inventory.py").write_text("# s\n")
    (mod / "manifest.json").write_text(
        json.dumps(
            {"activity": {"actions": {"receive": {"running": "Receiving stock…", "done": "Stock received"}}}}
        )
    )
    monkeypatch.setattr(
        "atria.core.modules.registry.resolve_modules_root", lambda: tmp_path
    )
    b = _broadcaster()
    args = {"command": f"python {mod}/scripts/inventory.py receive --sku A"}
    assert b._activity_for("bash_execute", args) == {
        "running": "Receiving stock…",
        "done": "Stock received",
    }


def test_activity_for_non_bash_is_none():
    assert _broadcaster()._activity_for("read_file", {"file_path": "/x"}) is None


def test_activity_for_non_module_bash_is_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "atria.core.modules.registry.resolve_modules_root", lambda: tmp_path
    )
    assert _broadcaster()._activity_for("bash_execute", {"command": "ls -la"}) is None
