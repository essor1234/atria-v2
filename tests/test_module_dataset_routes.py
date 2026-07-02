"""HTTP integration tests for the editable-dataset read/write routes."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from atria.core.modules import store  # noqa: E402
from atria.core.modules.registry import ModuleRegistry  # noqa: E402
from atria.web.dependencies import get_modules_registry  # noqa: E402
from atria.web.routes.modules import router as modules_router  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    store.create_module(tmp_path, "demo", template="data")
    store.write_data_files(tmp_path, "demo", [("wc.csv", b"Year,Winner\n2018,France\n")])
    reg = ModuleRegistry(tmp_path)
    reg.load_all()

    app = FastAPI()
    app.include_router(modules_router)
    app.dependency_overrides[get_modules_registry] = lambda: reg
    return TestClient(app), tmp_path


def test_read_then_write_round_trip(client):
    c, tmp_path = client

    r = c.get("/api/modules/demo/data/read", params={"file": "wc.csv"})
    assert r.status_code == 200
    body = r.json()
    assert [col["name"] for col in body["columns"]] == ["Year", "Winner"]
    assert body["rows"] == [{"Year": "2018", "Winner": "France"}]

    new = {
        "file": "wc.csv",
        "columns": [{"name": "Year"}, {"name": "Winner"}],
        "rows": [{"Year": "2018", "Winner": "France"}, {"Year": "2026", "Winner": "TBD"}],
    }
    w = c.put("/api/modules/demo/data/write", json=new)
    assert w.status_code == 200
    assert w.json()["ok"] is True
    assert w.json()["rows"] == 2

    # CSV on disk reflects the edit, and a backup exists.
    csv_text = (tmp_path / "demo" / "data" / "wc.csv").read_text(encoding="utf-8")
    assert "2026,TBD" in csv_text
    assert (tmp_path / "demo" / "data" / "wc.csv.bak").is_file()


def test_write_bad_path_returns_4xx_not_500(client):
    c, _ = client
    w = c.put(
        "/api/modules/demo/data/write",
        json={"file": "../escape.csv", "columns": ["a"], "rows": [{"a": "1"}]},
    )
    assert w.status_code == 400  # validation surfaces as 4xx, never a 500 crash


def test_read_missing_module_returns_404(client):
    c, _ = client
    r = c.get("/api/modules/nope/data/read", params={"file": "wc.csv"})
    assert r.status_code == 404


def test_write_preserves_custom_module_skill(tmp_path):
    # A custom module (no scripts/data.py) must keep its hand-authored SKILL.md
    # when its dataset is edited — the write route must NOT regenerate it.
    store.create_module(tmp_path, "custom", template="skill")
    store.write_data_files(tmp_path, "custom", [("inv.csv", b"a,b\n1,2\n")])
    marker = "# custom\n\nMY HAND-WRITTEN SKILL — do not clobber.\n"
    (tmp_path / "custom" / "SKILL.md").write_text(marker, encoding="utf-8")

    reg = ModuleRegistry(tmp_path)
    reg.load_all()
    app = FastAPI()
    app.include_router(modules_router)
    app.dependency_overrides[get_modules_registry] = lambda: reg
    c = TestClient(app)

    w = c.put(
        "/api/modules/custom/data/write",
        json={"file": "inv.csv", "columns": ["a", "b"], "rows": [{"a": "9", "b": "8"}]},
    )
    assert w.status_code == 200
    assert (tmp_path / "custom" / "SKILL.md").read_text(encoding="utf-8") == marker
    # but the data was still written
    assert "9,8" in (tmp_path / "custom" / "data" / "inv.csv").read_text(encoding="utf-8")
