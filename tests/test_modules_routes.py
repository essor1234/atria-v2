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
    body = r.json()
    assert body["name"] == "demo"
    assert "SKILL.md" in body["files"]
    r = client.get("/api/modules")
    assert [m["name"] for m in r.json()] == ["demo"]
    r = client.get("/api/modules/demo")
    assert r.status_code == 200
    assert "# demo" in r.json()["skill_md"]


def test_get_surfaces_description_from_frontmatter(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    skill = (
        "---\n"
        "name: demo\n"
        "description: Demo module for inventory stuff.\n"
        "---\n\n"
        "# demo\n\nBody prose.\n"
    )
    r = client.put(
        "/api/modules/demo/fs/write",
        json={"path": "SKILL.md", "content": skill},
    )
    assert r.status_code == 204, r.text
    r = client.get("/api/modules/demo")
    assert r.status_code == 200
    assert r.json()["description"] == "Demo module for inventory stuff."
    # And the list endpoint carries it too.
    r = client.get("/api/modules")
    assert r.json()[0]["description"] == "Demo module for inventory stuff."


def test_create_with_dashboard_template(client: TestClient):
    r = client.post("/api/modules", json={"name": "demo", "template": "skill_dashboard"})
    assert r.status_code == 201, r.text
    files = r.json()["files"]
    assert "scripts/main.py" in files
    assert "templates/dashboard.html" in files


def test_create_duplicate_returns_409(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.post("/api/modules", json={"name": "demo"})
    assert r.status_code == 409


def test_create_invalid_name_returns_400(client: TestClient):
    r = client.post("/api/modules", json={"name": "Bad Name"})
    assert r.status_code == 400


def test_fs_list_root_and_subdir(client: TestClient):
    client.post("/api/modules", json={"name": "demo", "template": "skill_dashboard"})
    r = client.get("/api/modules/demo/fs/list")
    assert r.status_code == 200
    names = sorted(e["name"] for e in r.json()["entries"])
    assert names == ["SKILL.md", "manifest.json", "scripts", "templates"]
    r = client.get("/api/modules/demo/fs/list", params={"path": "scripts"})
    assert [e["name"] for e in r.json()["entries"]] == ["main.py"]


def test_fs_write_then_read(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.put(
        "/api/modules/demo/fs/write",
        json={"path": "scripts/foo.py", "content": "print('hi')\n"},
    )
    assert r.status_code == 204
    r = client.get("/api/modules/demo/fs/read", params={"path": "scripts/foo.py"})
    assert r.status_code == 200
    assert r.text == "print('hi')\n"


def test_fs_write_rejects_traversal(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.put(
        "/api/modules/demo/fs/write",
        json={"path": "../escape.txt", "content": "x"},
    )
    assert r.status_code == 400


def test_fs_delete_protects_skill(client: TestClient):
    client.post("/api/modules", json={"name": "demo", "template": "skill_script"})
    r = client.delete("/api/modules/demo/fs/file", params={"path": "SKILL.md"})
    assert r.status_code == 400
    r = client.delete("/api/modules/demo/fs/file", params={"path": "scripts/main.py"})
    assert r.status_code == 204


def test_fs_read_missing_returns_404(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.get("/api/modules/demo/fs/read", params={"path": "scripts/missing.py"})
    assert r.status_code == 404


def test_delete_removes_and_subsequent_get_404s(client: TestClient):
    client.post("/api/modules", json={"name": "demo"})
    r = client.delete("/api/modules/demo")
    assert r.status_code == 204
    r = client.get("/api/modules/demo")
    assert r.status_code == 404


def test_list_has_dashboard_filter(client: TestClient):
    client.post("/api/modules", json={"name": "with-dash"})
    client.post("/api/modules", json={"name": "no-dash"})
    from atria.web.dependencies.modules import get_modules_registry
    reg = client.app.dependency_overrides[get_modules_registry]()
    (reg.root / "with-dash" / "dashboard.html").write_text("<html></html>")
    reg.reload_one("with-dash")

    r = client.get("/api/modules?has_dashboard=1")
    assert r.status_code == 200
    names = [m["name"] for m in r.json()]
    assert names == ["with-dash"]

    r = client.get("/api/modules")
    names = [m["name"] for m in r.json()]
    assert set(names) == {"with-dash", "no-dash"}
