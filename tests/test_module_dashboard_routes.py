from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.modules.registry import ModuleRegistry
from atria.web.dependencies.modules import get_modules_registry
from atria.web.routes.module_dashboard import router as dashboard_router


@pytest.fixture()
def warehouse_module(tmp_path: Path) -> Path:
    mod = tmp_path / "warehouse"
    (mod / "scripts").mkdir(parents=True)
    (mod / "SKILL.md").write_text("# warehouse\n")
    (mod / "scripts" / "echo.py").write_text(
        "#!/usr/bin/env python\n"
        "import sys, time, json, os\n"
        "cmd = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if cmd == 'sleep':\n"
        "    time.sleep(float(sys.argv[2]))\n"
        "elif cmd == 'env':\n"
        "    print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('ATRIA_')}))\n"
        "elif cmd == 'fail':\n"
        "    sys.stderr.write('boom\\n'); sys.exit(2)\n"
        "else:\n"
        "    print('echo:' + cmd)\n"
    )
    return tmp_path


@pytest.fixture()
def client(warehouse_module: Path) -> TestClient:
    app = FastAPI()
    app.include_router(dashboard_router)
    reg = ModuleRegistry(warehouse_module)
    reg.load_all()
    app.dependency_overrides[get_modules_registry] = lambda: reg
    return TestClient(app)


def test_run_happy_path(client: TestClient):
    r = client.post("/api/modules/warehouse/run", json={"script": "echo.py", "args": ["hi"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exit_code"] == 0
    assert body["stdout"].strip() == "echo:hi"
    assert body["stderr"] == ""
    assert body["duration_ms"] >= 0


def test_run_non_zero_returns_200_with_exit_code(client: TestClient):
    r = client.post("/api/modules/warehouse/run", json={"script": "echo.py", "args": ["fail"]})
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 2
    assert "boom" in body["stderr"]


def test_run_unknown_script_returns_404(client: TestClient):
    r = client.post("/api/modules/warehouse/run", json={"script": "ghost.py", "args": []})
    assert r.status_code == 404
    assert r.json()["detail"]["kind"] == "unknown-script"


def test_run_path_escape_rejected(client: TestClient):
    for bad in ["../etc/passwd", "/absolute", "scripts/../../../x"]:
        r = client.post("/api/modules/warehouse/run", json={"script": bad, "args": []})
        assert r.status_code == 400, bad
        assert r.json()["detail"]["kind"] == "path-escape"


def test_run_timeout(client: TestClient):
    r = client.post(
        "/api/modules/warehouse/run",
        json={"script": "echo.py", "args": ["sleep", "5"], "timeout_ms": 200},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == -1
    assert "timeout" in body["stderr"].lower()


def test_run_passes_module_env(client: TestClient, warehouse_module: Path):
    r = client.post("/api/modules/warehouse/run", json={"script": "echo.py", "args": ["env"]})
    assert r.status_code == 200
    import json

    env = json.loads(r.json()["stdout"])
    assert env["ATRIA_MODULE_ROOT"] == str((warehouse_module / "warehouse").resolve())


def test_run_unknown_module_returns_404(client: TestClient):
    r = client.post("/api/modules/nope/run", json={"script": "echo.py", "args": []})
    assert r.status_code == 404


def test_run_concurrency_rate_limited(client: TestClient):
    from concurrent.futures import ThreadPoolExecutor

    def _fire(_: int):
        return client.post(
            "/api/modules/warehouse/run",
            json={"script": "echo.py", "args": ["sleep", "0.5"], "timeout_ms": 5000},
        )

    with ThreadPoolExecutor(max_workers=6) as ex:
        responses = list(ex.map(_fire, range(6)))

    statuses = [resp.status_code for resp in responses]
    assert sum(1 for s in statuses if s == 200) >= 4, statuses
    rate_limited = [resp for resp in responses if resp.status_code == 429]
    assert rate_limited, f"expected at least one 429 response, got {statuses}"
    assert rate_limited[0].json()["detail"]["kind"] == "rate-limited"


def test_bridge_js_served(client: TestClient):
    r = client.get("/api/modules/warehouse/__bridge.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert "AtriaDash" in r.text
    assert "AtriaBlock" in r.text


def test_base_css_served(client: TestClient):
    r = client.get("/api/modules/warehouse/__base.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert ":root" in r.text


def test_virtual_assets_resolve_per_module(client: TestClient):
    r1 = client.get("/api/modules/warehouse/__bridge.js")
    assert r1.status_code == 200


def test_virtual_unknown_path_404(client: TestClient):
    r = client.get("/api/modules/warehouse/__nope.js")
    assert r.status_code == 404


def test_dashboard_html_served_when_present(client: TestClient, warehouse_module: Path):
    (warehouse_module / "warehouse" / "dashboard.html").write_text("<!doctype html><body>hi</body>")
    r = client.get("/api/modules/warehouse/dashboard.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "hi" in r.text


def test_dashboard_html_404_when_absent(client: TestClient):
    r = client.get("/api/modules/warehouse/dashboard.html")
    assert r.status_code == 404


def test_block_html_served(client: TestClient, warehouse_module: Path):
    (warehouse_module / "warehouse" / "blocks").mkdir()
    (warehouse_module / "warehouse" / "blocks" / "item_form.html").write_text(
        "<!doctype html><body>form</body>"
    )
    r = client.get("/api/modules/warehouse/blocks/item_form.html")
    assert r.status_code == 200
    assert "form" in r.text


def test_module_vendor_file_served(client: TestClient, warehouse_module: Path):
    (warehouse_module / "warehouse" / "vendor").mkdir()
    (warehouse_module / "warehouse" / "vendor" / "x.js").write_text("console.log('hi');")
    r = client.get("/api/modules/warehouse/vendor/x.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_icon_svg_served(client: TestClient, warehouse_module: Path):
    (warehouse_module / "warehouse" / "icon.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'/>"
    )
    r = client.get("/api/modules/warehouse/icon.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg")


def test_physical_path_escape_rejected(client: TestClient):
    r = client.get("/api/modules/warehouse/blocks/../../etc/passwd")
    assert r.status_code in (400, 404)
