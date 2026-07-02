from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.web.routes import module_dashboard
from atria.core.modules.registry import ModuleRegistry


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "modules"
    # demo module — has rpc.py
    mod = root / "demo" / "scripts"
    mod.mkdir(parents=True)
    (root / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")
    (mod / "rpc.py").write_text(
        "import sys, json\n"
        "req = json.load(sys.stdin)\n"
        "print(json.dumps({'echo': req['payload'], 'method': req['method']}))\n"
    )
    # demo_norpc module — has SKILL.md but NO rpc.py
    (root / "demo_norpc").mkdir(parents=True)
    (root / "demo_norpc" / "SKILL.md").write_text("---\nname: demo_norpc\n---\n")

    reg = ModuleRegistry(root=root)
    reg.load_all()
    app = FastAPI()
    app.include_router(module_dashboard.router)
    app.dependency_overrides[module_dashboard.get_modules_registry] = lambda: reg
    return TestClient(app)


def test_module_rpc_echo(client):
    resp = client.post(
        "/api/modules/demo/rpc",
        json={"method": "ping", "payload": {"x": 1}},
        headers={"x-atria-session-id": "s1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["echo"] == {"x": 1}
    assert body["data"]["method"] == "ping"


def test_module_rpc_missing_handler(client):
    """A module without scripts/rpc.py must return 404 with kind=unknown-rpc-handler."""
    resp = client.post(
        "/api/modules/demo_norpc/rpc",
        json={"method": "ping", "payload": {}},
    )
    assert resp.status_code == 404
    detail = resp.json().get("detail", {})
    assert detail.get("kind") == "unknown-rpc-handler"
