from pathlib import Path

from atria.core.modules.store import _read_manifest

WAREHOUSE = Path(__file__).resolve().parents[1] / "modules" / "warehouse"


def test_warehouse_manifest_has_receive_label():
    manifest = _read_manifest(WAREHOUSE)
    assert manifest is not None
    assert "receive" in manifest.activity_actions
    assert manifest.activity_actions["receive"].running == "Receiving stock…"
    assert manifest.activity_default is not None
