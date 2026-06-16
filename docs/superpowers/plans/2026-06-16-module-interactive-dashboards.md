# Module Interactive Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any module under `modules/<name>/` ship `dashboard.html`. It surfaces as a button in the left sidebar; clicking the button replaces the chat view with the dashboard. The dashboard runs JS in a sandboxed iframe and can execute the module's scripts directly via `AtriaDash.run()`, with CSV/file changes flowing back live via the existing module watcher.

**Architecture:** Single new backend router under `/api/modules/<name>/` that serves `dashboard.html`, virtual platform helpers (`__bridge.js`, `__base.css`, `__vendor/*`), and accepts `POST .../run` to spawn the module's scripts. Existing watcher (already wired to broadcast `modules.changed`) is reused. Frontend adds a Zustand `modules` store, a sidebar Modules group with one button per module, and a `ModuleDashboardView` that mounts the iframe and proxies postMessage to/from the host. The existing `blocks/` HTML files migrate to the same URL prefix, killing the global `/static/blocks/` dependency.

**Tech Stack:** FastAPI + Pydantic v2 (backend), pytest + FastAPI TestClient (backend tests), React 18 + Zustand + Tailwind + lucide-react + motion (frontend), Vitest (the few existing frontend tests), Python 3 subprocess for `run`. Spec source: `docs/superpowers/specs/2026-06-16-module-interactive-dashboards-design.md`.

**Conventions for this plan:**
- All paths absolute from repo root `/Users/anlnm/Desktop/Project/opendev-py/`.
- Backend tests under `tests/` follow `test_modules_routes.py` style (FastAPI TestClient against a freshly-mounted router with a `tmp_path` registry).
- Frontend changes ship without unit tests unless the repo already tests the affected module (verified per task). Manual smoke tests called out explicitly.
- Commit after every task. Never skip a step.

---

## File Structure

```
atria/
  web/
    routes/
      module_dashboard.py        NEW. Per-module dashboard + run routes.
      __init__.py                MODIFY. Export module_dashboard_router.
    dashboard_assets/            NEW dir.
      __bridge.js                NEW. AtriaDash + AtriaBlock globals.
      __base.css                 NEW. CSS reset + theme-token vars.
      vendor/
        chartjs@4/chart.min.js   NEW. Pinned platform vendor.
        htmx@2/htmx.min.js       NEW. Pinned platform vendor.
    server.py                    MODIFY. Register new router; remove
                                 legacy /modules/{name}/blocks/{...}.
    routes/modules.py            MODIFY. Add ?has_dashboard=1 filter.

modules/warehouse/
  dashboard.html                 NEW.
  icon.svg                       NEW.
  scripts/inventory.py           MODIFY. Add --json on `list`.
  blocks/item_form.html          MODIFY. Switch to __bridge.js / __base.css.

web-ui/src/
  stores/
    modules.ts                   NEW. Zustand: modulesWithDashboards,
                                 activeModuleDashboard, badges.
  components/
    Layout/ProjectSidebar.tsx    MODIFY. Add Modules group + buttons.
    ModuleDashboard/
      ModuleDashboardView.tsx    NEW. Main-pane view with iframe + header.
      useModuleBridge.ts         NEW. postMessage bridge hook.
  pages/ChatPage.tsx             MODIFY. Swap ChatView ↔ ModuleDashboardView.

tests/
  test_module_dashboard_routes.py  NEW. Coverage for run/assets/files.
  test_warehouse_inventory.py      NEW. Coverage for `list --json`.

docs/superpowers/specs/
  2026-06-16-module-interactive-dashboards-design.md  (already committed)
```

---

## Task 1: Backend — `POST /api/modules/<name>/run` subprocess gateway

**Files:**
- Create: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`
- Create: `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`

- [ ] **Step 1: Write failing tests for `run` happy path + path-escape + unknown-script + timeout + rate-limit**

Create `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.modules.registry import ModuleRegistry
from atria.web.dependencies.modules import get_modules_registry
from atria.web.routes.module_dashboard import router as dashboard_router


@pytest.fixture()
def warehouse_module(tmp_path: Path) -> Path:
    """Create a minimal warehouse-like module on disk."""
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
    r = client.post(
        "/api/modules/warehouse/run",
        json={"script": "echo.py", "args": ["hi"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exit_code"] == 0
    assert body["stdout"].strip() == "echo:hi"
    assert body["stderr"] == ""
    assert body["duration_ms"] >= 0


def test_run_non_zero_returns_200_with_exit_code(client: TestClient):
    r = client.post(
        "/api/modules/warehouse/run",
        json={"script": "echo.py", "args": ["fail"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exit_code"] == 2
    assert "boom" in body["stderr"]


def test_run_unknown_script_returns_404(client: TestClient):
    r = client.post(
        "/api/modules/warehouse/run",
        json={"script": "ghost.py", "args": []},
    )
    assert r.status_code == 404
    assert r.json()["kind"] == "unknown-script"


def test_run_path_escape_rejected(client: TestClient):
    for bad in ["../etc/passwd", "/absolute", "scripts/../../../x"]:
        r = client.post(
            "/api/modules/warehouse/run",
            json={"script": bad, "args": []},
        )
        assert r.status_code == 400, bad
        assert r.json()["kind"] == "path-escape"


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
    r = client.post(
        "/api/modules/warehouse/run",
        json={"script": "echo.py", "args": ["env"]},
    )
    assert r.status_code == 200
    import json
    env = json.loads(r.json()["stdout"])
    assert env["ATRIA_MODULE_ROOT"] == str((warehouse_module / "warehouse").resolve())


def test_run_unknown_module_returns_404(client: TestClient):
    r = client.post(
        "/api/modules/nope/run",
        json={"script": "echo.py", "args": []},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail (route doesn't exist yet)**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py -v`
Expected: collection error / ModuleNotFoundError on `atria.web.routes.module_dashboard`.

- [ ] **Step 3: Implement the route**

Create `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`:

```python
"""Per-module dashboard + script-run HTTP gateway.

All URLs the dashboard iframe loads sit under ``/api/modules/<name>/``:

- ``POST /api/modules/<name>/run`` — spawn ``modules/<name>/scripts/<script>``
  in a subprocess. Buffered stdout/stderr returned. Path escape rejected.
- ``GET  /api/modules/<name>/dashboard.html`` — file on disk (Task 3).
- ``GET  /api/modules/<name>/__bridge.js`` — virtual platform asset (Task 2).
- ``GET  /api/modules/<name>/blocks/<file>`` — existing block HTML (Task 3).

Concurrency: at most 4 in-flight ``run`` calls per (session, module).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import InvalidModuleName
from atria.web.dependencies.modules import get_modules_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/modules", tags=["module-dashboard"])

DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 120_000
MAX_CONCURRENT_PER_KEY = 4

# (session_id, module_name) -> current in-flight count.
_inflight_lock = threading.Lock()
_inflight: Dict[tuple, int] = defaultdict(int)


class RunBody(BaseModel):
    script: str = Field(min_length=1)
    args: List[str] = Field(default_factory=list)
    stdin: Optional[str] = None
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, ge=1, le=MAX_TIMEOUT_MS)


def _err(status: int, kind: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"kind": kind, "message": message})


def _resolve_script(reg: ModuleRegistry, module_name: str, script: str) -> Path:
    """Resolve ``modules/<module_name>/scripts/<script>`` and reject traversal."""
    try:
        module_dir = (reg.root / module_name).resolve()
    except (OSError, ValueError) as exc:
        raise _err(400, "path-escape", str(exc))
    if not module_dir.is_dir():
        raise _err(404, "unknown-module", f"module {module_name!r} not found")

    if script.startswith("/") or script.startswith("\\"):
        raise _err(400, "path-escape", "absolute path not allowed")
    scripts_dir = (module_dir / "scripts").resolve()
    target = (scripts_dir / script).resolve()
    try:
        target.relative_to(scripts_dir)
    except ValueError:
        raise _err(400, "path-escape", "path escapes scripts/")
    if not target.is_file():
        raise _err(404, "unknown-script", f"script {script!r} not found")
    return target


def _acquire_slot(key: tuple) -> bool:
    with _inflight_lock:
        if _inflight[key] >= MAX_CONCURRENT_PER_KEY:
            return False
        _inflight[key] += 1
        return True


def _release_slot(key: tuple) -> None:
    with _inflight_lock:
        n = _inflight[key] - 1
        if n <= 0:
            _inflight.pop(key, None)
        else:
            _inflight[key] = n


def _session_id_from(request: Request) -> str:
    # In tests there is no real session cookie; default to "test". The frontend
    # always sends the session id as a cookie or header; we read both.
    cookie = request.cookies.get("session_id")
    if cookie:
        return cookie
    header = request.headers.get("x-atria-session-id")
    if header:
        return header
    return "default"


@router.post("/{name}/run")
def run_endpoint(
    name: str,
    body: RunBody,
    request: Request,
    reg: ModuleRegistry = Depends(get_modules_registry),
) -> Dict[str, Any]:
    try:
        # Validate name format up-front to surface 400 not 404.
        reg.root  # noqa: B018 (touch to assert reg is alive)
    except Exception as exc:  # noqa: BLE001
        raise _err(500, "registry-error", str(exc))

    try:
        target = _resolve_script(reg, name, body.script)
    except HTTPException:
        raise
    except InvalidModuleName as exc:
        raise _err(400, "invalid-module-name", str(exc))

    session_id = _session_id_from(request)
    key = (session_id, name)
    if not _acquire_slot(key):
        raise _err(429, "rate-limited", f"max {MAX_CONCURRENT_PER_KEY} concurrent runs per session+module")

    env = os.environ.copy()
    env["ATRIA_SESSION_ID"] = session_id
    env["ATRIA_MODULE_ROOT"] = str((reg.root / name).resolve())
    api_base = env.get("ATRIA_API_BASE") or "http://127.0.0.1:8000"
    env["ATRIA_API_BASE"] = api_base

    timeout_s = body.timeout_ms / 1000.0
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(target), *body.args],
            input=body.stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        out = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or "")
        err_text = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, (bytes, bytearray)) else (exc.stderr or "")
        return {
            "exit_code": -1,
            "stdout": out,
            "stderr": (err_text + f"\n[atria] script timed out after {body.timeout_ms} ms").strip(),
            "duration_ms": duration_ms,
        }
    except FileNotFoundError as exc:
        raise _err(500, "spawn-failed", str(exc))
    finally:
        _release_slot(key)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add atria/web/routes/module_dashboard.py tests/test_module_dashboard_routes.py
git commit -m "feat(modules): POST /api/modules/<name>/run subprocess gateway

Path-escape, unknown-script, timeout, and per-(session, module) concurrency
cap (4 in-flight). Returns buffered stdout/stderr + exit_code + duration."
```

---

## Task 2: Backend — Virtual platform assets (`__bridge.js`, `__base.css`, `__vendor/*`)

**Files:**
- Create: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/dashboard_assets/__bridge.js`
- Create: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/dashboard_assets/__base.css`
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`

- [ ] **Step 1: Add failing tests for virtual asset routes**

Append to `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`:

```python
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
    # Same content regardless of module — but route must accept any valid name.
    r1 = client.get("/api/modules/warehouse/__bridge.js")
    assert r1.status_code == 200


def test_virtual_unknown_path_404(client: TestClient):
    r = client.get("/api/modules/warehouse/__nope.js")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py::test_bridge_js_served -v`
Expected: 404 (route not registered).

- [ ] **Step 3: Create the bridge JS asset**

Create `/Users/anlnm/Desktop/Project/opendev-py/atria/web/dashboard_assets/__bridge.js`:

```javascript
/*! AtriaDash + AtriaBlock host bridge. Loaded inside the dashboard iframe.
 *  Communicates with the parent React app via postMessage. No imports.
 */
(function () {
  "use strict";

  var listeners = {
    theme: [],
    context: [],
    change: [],
    visibility: [],
    props: [],
  };
  var pending = {};   // requestId -> {resolve, reject}
  var nextId = 1;

  function uuid() {
    return "r-" + (nextId++) + "-" + Math.floor(Math.random() * 1e9).toString(36);
  }

  function fire(name, payload) {
    var arr = listeners[name];
    if (!arr) return;
    for (var i = 0; i < arr.length; i++) {
      try { arr[i](payload); } catch (e) { console.error(e); }
    }
  }

  function send(msg) {
    parent.postMessage(msg, "*");
  }

  window.addEventListener("message", function (ev) {
    var msg = ev.data || {};
    if (!msg || typeof msg.type !== "string") return;

    if (msg.type === "theme")      return fire("theme", msg.tokens || {});
    if (msg.type === "context")    return fire("context", {
      sessionId: msg.sessionId, moduleName: msg.moduleName, moduleRoot: msg.moduleRoot,
    });
    if (msg.type === "change")     return fire("change", msg.paths || []);
    if (msg.type === "visibility") return fire("visibility", !!msg.visible);
    if (msg.type === "props")      return fire("props", msg.props || {});

    if (msg.type === "run:result") {
      var p = pending[msg.requestId];
      if (!p) return;
      delete pending[msg.requestId];
      p.resolve({
        exit_code: msg.exit_code,
        stdout: msg.stdout || "",
        stderr: msg.stderr || "",
        duration_ms: msg.duration_ms || 0,
      });
    }
    if (msg.type === "run:error") {
      var pe = pending[msg.requestId];
      if (!pe) return;
      delete pending[msg.requestId];
      var err = new Error(msg.message || msg.kind || "run failed");
      err.kind = msg.kind || "unknown";
      pe.reject(err);
    }
  });

  function onify(name) {
    return function (fn) { if (typeof fn === "function") listeners[name].push(fn); };
  }

  var AtriaDash = {
    onTheme:      onify("theme"),
    onContext:    onify("context"),
    onChange:     onify("change"),
    onVisibility: onify("visibility"),

    ready: function () { send({ type: "ready" }); },

    run: function (script, args, opts) {
      var requestId = uuid();
      var msg = {
        type: "run", requestId: requestId,
        script: script, args: args || [],
      };
      if (opts) {
        if (opts.stdin != null) msg.stdin = String(opts.stdin);
        if (opts.timeout_ms) msg.timeout_ms = opts.timeout_ms | 0;
      }
      return new Promise(function (resolve, reject) {
        pending[requestId] = { resolve: resolve, reject: reject };
        send(msg);
      });
    },

    json: function (script, args, opts) {
      return AtriaDash.run(script, args, opts).then(function (res) {
        if (res.exit_code !== 0) {
          var e = new Error("non-zero exit (" + res.exit_code + "): " + (res.stderr || ""));
          e.kind = "non-zero"; e.result = res;
          throw e;
        }
        try { return JSON.parse(res.stdout); }
        catch (parseErr) {
          var e2 = new Error("stdout is not valid JSON: " + parseErr.message);
          e2.kind = "bad-json"; e2.result = res;
          throw e2;
        }
      });
    },

    setBadge: function (value) { send({ type: "badge", value: value || null }); },
    setTitle: function (text)  { send({ type: "title", text: String(text || "") }); },
    toast:    function (opts)  { send({ type: "toast",
                                        message: String((opts && opts.message) || ""),
                                        severity: (opts && opts.severity) || "info" }); },
    openBlock: function (block, props) {
      send({ type: "openBlock", block: String(block || ""), props: props || {} });
    },
    openChat: function () { send({ type: "openChat" }); },

    resize: function (height) { send({ type: "resize", height: height | 0 }); },
  };

  // ── AtriaBlock (for push_block iframes) ──────────────────────────────────
  // Same wire protocol; thin alias so existing block HTML keeps working.
  var AtriaBlock = {
    onTheme:  AtriaDash.onTheme,
    onProps:  onify("props"),
    ready:    AtriaDash.ready,
    resize:   AtriaDash.resize,
    emit:     function (name, payload) {
      send({ type: "block-event", name: String(name || ""), payload: payload || {} });
    },
  };

  window.AtriaDash = AtriaDash;
  window.AtriaBlock = AtriaBlock;
})();
```

- [ ] **Step 4: Create the base CSS asset**

Create `/Users/anlnm/Desktop/Project/opendev-py/atria/web/dashboard_assets/__base.css`:

```css
/* AtriaDash + AtriaBlock base styles. Injected into iframes. */
:root {
  color-scheme: light dark;
  --card: 0 0% 100%;
  --card-foreground: 222 47% 11%;
  --muted: 215 16% 47%;
  --muted-foreground: 215 16% 47%;
  --primary: 222 47% 11%;
  --primary-foreground: 0 0% 100%;
  --border: 214 32% 91%;
  --background: 0 0% 100%;
}

@media (prefers-color-scheme: dark) {
  :root {
    --card: 222 47% 11%;
    --card-foreground: 210 40% 96%;
    --muted: 215 20% 65%;
    --muted-foreground: 215 20% 65%;
    --primary: 210 40% 96%;
    --primary-foreground: 222 47% 11%;
    --border: 217 19% 27%;
    --background: 222 47% 11%;
  }
}

*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  color: hsl(var(--card-foreground));
  background: hsl(var(--background));
  font-size: 14px;
  line-height: 1.5;
}
```

- [ ] **Step 5: Register the virtual asset routes**

Append to `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`:

```python
# ── Virtual platform assets ─────────────────────────────────────────────────

from fastapi.responses import Response

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "dashboard_assets"

_VIRTUAL_MIME = {
    "__bridge.js": "application/javascript; charset=utf-8",
    "__base.css":  "text/css; charset=utf-8",
}


def _serve_asset(rel: str, mime: str) -> Response:
    p = (_ASSETS_DIR / rel).resolve()
    try:
        p.relative_to(_ASSETS_DIR)
    except ValueError:
        raise _err(404, "not-found", "asset not found")
    if not p.is_file():
        raise _err(404, "not-found", "asset not found")
    return Response(
        content=p.read_bytes(),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/{name}/__bridge.js")
def serve_bridge(name: str) -> Response:
    return _serve_asset("__bridge.js", _VIRTUAL_MIME["__bridge.js"])


@router.get("/{name}/__base.css")
def serve_base_css(name: str) -> Response:
    return _serve_asset("__base.css", _VIRTUAL_MIME["__base.css"])


@router.get("/{name}/__vendor/{lib}/{filename:path}")
def serve_vendor(name: str, lib: str, filename: str) -> Response:
    import mimetypes
    rel = f"vendor/{lib}/{filename}"
    mime, _ = mimetypes.guess_type(filename)
    if mime is None:
        mime = "application/octet-stream"
    return _serve_asset(rel, mime)
```

- [ ] **Step 6: Run tests to verify pass**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py -v -k bridge_js or base_css or virtual`
Expected: all virtual-asset tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add atria/web/dashboard_assets/__bridge.js atria/web/dashboard_assets/__base.css \
        atria/web/routes/module_dashboard.py tests/test_module_dashboard_routes.py
git commit -m "feat(modules): virtual __bridge.js + __base.css + __vendor routes

Per-module URL prefix /api/modules/<name>/ now serves the AtriaDash/AtriaBlock
bridge, base CSS tokens, and platform vendor libs without any module-side
duplication. Cache 5 min."
```

---

## Task 3: Backend — Physical file routes (`dashboard.html`, `icon.svg`, `blocks/*`, `vendor/*`)

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`

- [ ] **Step 1: Add failing tests**

Append to `/Users/anlnm/Desktop/Project/opendev-py/tests/test_module_dashboard_routes.py`:

```python
def test_dashboard_html_served_when_present(client: TestClient, warehouse_module: Path):
    (warehouse_module / "warehouse" / "dashboard.html").write_text(
        "<!doctype html><body>hi</body>"
    )
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
    (warehouse_module / "warehouse" / "vendor" / "x.js").write_text(
        "console.log('hi');"
    )
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
```

- [ ] **Step 2: Run tests; observe failures**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py -v -k "dashboard_html or block_html or module_vendor or icon_svg or physical_path"`
Expected: all failing (no routes registered).

- [ ] **Step 3: Implement physical-file routes**

Append to `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/module_dashboard.py`:

```python
# ── Module-owned physical files ─────────────────────────────────────────────

import mimetypes

from atria.core.modules import store as _store
from atria.core.modules.store import ModuleNotFound


def _serve_module_file(reg: ModuleRegistry, name: str, rel: str) -> Response:
    try:
        data = _store.read_file(reg.root, name, rel)
    except InvalidModuleName as exc:
        raise _err(400, "invalid-module-name", str(exc))
    except ModuleNotFound:
        raise _err(404, "unknown-module", f"module {name!r} not found")
    except FileNotFoundError:
        raise _err(404, "not-found", "file not found")
    except ValueError as exc:
        raise _err(400, "path-escape", str(exc))
    mime, _ = mimetypes.guess_type(rel)
    if mime is None:
        mime = "application/octet-stream"
    return Response(
        content=data, media_type=mime, headers={"Cache-Control": "no-cache"}
    )


@router.get("/{name}/dashboard.html")
def serve_dashboard_html(name: str, reg: ModuleRegistry = Depends(get_modules_registry)) -> Response:
    return _serve_module_file(reg, name, "dashboard.html")


@router.get("/{name}/icon.svg")
def serve_icon_svg(name: str, reg: ModuleRegistry = Depends(get_modules_registry)) -> Response:
    return _serve_module_file(reg, name, "icon.svg")


@router.get("/{name}/blocks/{filename:path}")
def serve_block_file(name: str, filename: str, reg: ModuleRegistry = Depends(get_modules_registry)) -> Response:
    return _serve_module_file(reg, name, f"blocks/{filename}")


@router.get("/{name}/vendor/{filename:path}")
def serve_module_vendor(name: str, filename: str, reg: ModuleRegistry = Depends(get_modules_registry)) -> Response:
    return _serve_module_file(reg, name, f"vendor/{filename}")
```

- [ ] **Step 4: Run tests; observe pass**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py -v`
Expected: all 17+ tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add atria/web/routes/module_dashboard.py tests/test_module_dashboard_routes.py
git commit -m "feat(modules): physical asset routes for dashboard/icon/blocks/vendor

GET /api/modules/<name>/{dashboard.html|icon.svg|blocks/*|vendor/*} reads
straight from the module folder. Path-escape rejected. 404 when absent."
```

---

## Task 4: Backend — Wire new router into the FastAPI app; drop legacy block route

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/__init__.py`
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/server.py`

- [ ] **Step 1: Read `atria/web/routes/__init__.py`**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && cat atria/web/routes/__init__.py`
Expected: a list of `*_router` re-exports.

- [ ] **Step 2: Add the new router export**

In `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/__init__.py`, append next to other router imports:

```python
from atria.web.routes.module_dashboard import router as module_dashboard_router
```

…and add `"module_dashboard_router"` to whatever `__all__` is present (if any).

- [ ] **Step 3: Register the router in `server.py` and delete the legacy `/modules/{name}/blocks/{filename:path}` route**

In `/Users/anlnm/Desktop/Project/opendev-py/atria/web/server.py`:

A) Add to the imports near the existing router imports:

```python
from atria.web.routes import (
    chat_router,
    sessions_router,
    config_router,
    commands_router,
    mcp_router,
    auth_router,
    projects_router,
    artifacts_router,
    fs_router,
    personas_router,
    analyze_router,
    modules_router,
    blocks_router,
    module_dashboard_router,   # NEW
)
```

B) After `app.include_router(blocks_router)` add:

```python
app.include_router(module_dashboard_router)
```

C) Delete the entire legacy handler:

```python
@app.get("/modules/{name}/blocks/{filename:path}")
async def serve_module_block(name: str, filename: str):
    ...
```

— remove that function and its decorator. The new router at
`/api/modules/<name>/blocks/...` supersedes it.

- [ ] **Step 4: Smoke-test the wiring with the existing test suite**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_modules_routes.py tests/test_module_dashboard_routes.py -v`
Expected: all green; no regression in existing module routes.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add atria/web/routes/__init__.py atria/web/server.py
git commit -m "chore(modules): register module_dashboard_router; drop legacy block route

The legacy /modules/{name}/blocks/{...} app-level handler is superseded
by the new /api/modules/<name>/blocks/* route registered through the
module_dashboard router."
```

---

## Task 5: Backend — `GET /api/modules?has_dashboard=1` filter

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/modules.py`
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/tests/test_modules_routes.py`

- [ ] **Step 1: Write failing test**

Append to `/Users/anlnm/Desktop/Project/opendev-py/tests/test_modules_routes.py`:

```python
def test_list_has_dashboard_filter(client: TestClient, tmp_path: Path):
    # Two modules; only one has dashboard.html on disk.
    client.post("/api/modules", json={"name": "with-dash"})
    client.post("/api/modules", json={"name": "no-dash"})
    # Fetch the modules registry root from the dependency override.
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
```

- [ ] **Step 2: Run test; observe failure (both lists return both modules)**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_modules_routes.py::test_list_has_dashboard_filter -v`

- [ ] **Step 3: Implement the filter**

In `/Users/anlnm/Desktop/Project/opendev-py/atria/web/routes/modules.py`, replace the `list_endpoint` definition:

```python
@router.get("", response_model=List[ModuleOut])
def list_endpoint(
    has_dashboard: bool = Query(False, alias="has_dashboard"),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    items = reg.all()
    if has_dashboard:
        items = [m for m in items if "dashboard.html" in m.files]
    return [_to_out(m) for m in items]
```

(Make sure `Query` is imported — it's already used elsewhere in the file.)

- [ ] **Step 4: Run test**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_modules_routes.py -v`
Expected: all pass including the new filter test.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add atria/web/routes/modules.py tests/test_modules_routes.py
git commit -m "feat(modules): GET /api/modules?has_dashboard=1 filter

Frontend uses this to decide which modules get a sidebar button without
re-scanning every module's file list client-side."
```

---

## Task 6: Module — `inventory.py list --json`

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/scripts/inventory.py`
- Create: `/Users/anlnm/Desktop/Project/opendev-py/tests/test_warehouse_inventory.py`

- [ ] **Step 1: Write failing test**

Create `/Users/anlnm/Desktop/Project/opendev-py/tests/test_warehouse_inventory.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "modules" / "warehouse" / "scripts" / "inventory.py"


@pytest.fixture()
def tmp_csv(tmp_path, monkeypatch):
    # The script writes to its bundled data/inventory.csv. Tests should not
    # mutate it. Instead, run the script with the bundled CSV in read-only
    # subcommands only.
    yield tmp_path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def test_list_json_returns_items_and_low_stock():
    r = _run("list", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert isinstance(payload["items"], list)
    assert all({"sku","name","location","quantity","unit_price","reorder_level"}
               .issubset(item.keys()) for item in payload["items"])
    assert isinstance(payload["low_stock"], list)
    # All low_stock entries must be SKUs of items at/under their reorder_level.
    by_sku = {it["sku"]: it for it in payload["items"]}
    for sku in payload["low_stock"]:
        it = by_sku[sku]
        assert int(it["quantity"]) <= int(it["reorder_level"])


def test_list_json_query_filter():
    r = _run("list", "--json", "--query", "widget")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert all("widget" in it["name"].lower() or "widget" in it["sku"].lower()
               for it in payload["items"])
```

- [ ] **Step 2: Run; observe failure (no --json flag yet)**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_warehouse_inventory.py -v`
Expected: fail — argparse rejects `--json`.

- [ ] **Step 3: Add `--json` to `inventory.py`**

In `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/scripts/inventory.py`:

A) In `cmd_list`, replace the function body with:

```python
def cmd_list(args: argparse.Namespace) -> int:
    rows = _load()
    if args.query:
        q = args.query.lower()
        rows = [r for r in rows if q in r["sku"].lower() or q in r["name"].lower()]

    low: list[str] = []
    for r in rows:
        try:
            if int(r["quantity"]) <= int(r["reorder_level"]):
                low.append(r["sku"])
        except ValueError:
            pass

    if args.json:
        import json as _json
        print(_json.dumps({"items": rows, "low_stock": low}))
        return 0

    if not rows:
        print("(no items)")
        return 0
    widths = {f: max(len(f), max((len(r.get(f, "")) for r in rows), default=0)) for f in FIELDS}
    line = "  ".join(f.ljust(widths[f]) for f in FIELDS)
    print(line)
    print("  ".join("-" * widths[f] for f in FIELDS))
    for r in rows:
        print("  ".join(r.get(f, "").ljust(widths[f]) for f in FIELDS))
    if low:
        print(f"\nlow stock (<= reorder_level): {', '.join(low)}")
    return 0
```

B) In `main()`, add the `--json` flag to the `p_list` subparser:

```python
    p_list = sub.add_parser("list", help="list items")
    p_list.add_argument("--query", help="substring filter on sku/name")
    p_list.add_argument("--json", action="store_true", help="emit JSON for programmatic consumers")
    p_list.set_defaults(fn=cmd_list)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_warehouse_inventory.py -v`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add modules/warehouse/scripts/inventory.py tests/test_warehouse_inventory.py
git commit -m "feat(warehouse): inventory.py list --json

Emits {items, low_stock} so dashboards can drive UI from one call instead
of re-parsing the CLI-shaped text output."
```

---

## Task 7: Module — `modules/warehouse/dashboard.html` + `icon.svg`

**Files:**
- Create: `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/dashboard.html`
- Create: `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/icon.svg`

- [ ] **Step 1: Create the icon**

Create `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/icon.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 7l9-4 9 4v10l-9 4-9-4V7z"/>
  <path d="M3 7l9 4 9-4"/>
  <path d="M12 11v10"/>
</svg>
```

- [ ] **Step 2: Create the dashboard HTML**

Create `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/dashboard.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>warehouse dashboard</title>
  <link rel="stylesheet" href="__base.css" />
  <style>
    .wrap   { padding: 20px; display: flex; flex-direction: column; gap: 20px; }
    .kpis   { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .kpi    { border: 1px solid hsl(var(--border)); border-radius: 10px; padding: 14px 16px;
              display: flex; flex-direction: column; gap: 2px; background: hsl(var(--card)); }
    .kpi h3 { margin: 0; font-size: 11px; color: hsl(var(--muted-foreground));
              font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; }
    .kpi b  { font-size: 22px; font-weight: 600; }
    .kpi.warn b { color: hsl(0 72% 51%); }
    .row    { display: grid; grid-template-columns: 1fr 80px 60px; gap: 10px;
              align-items: center; padding: 8px 10px; border-radius: 6px; }
    .row + .row { border-top: 1px solid hsl(var(--border)); }
    .row .name  { font-weight: 500; }
    .row .qty   { font-variant-numeric: tabular-nums; text-align: right; }
    .row .actions { display: flex; gap: 4px; justify-content: flex-end; }
    button  { font: inherit; border: 1px solid hsl(var(--border)); background: hsl(var(--card));
              color: hsl(var(--card-foreground)); border-radius: 6px;
              padding: 4px 8px; cursor: pointer; }
    button.primary { background: hsl(var(--primary)); color: hsl(var(--primary-foreground)); border: 0; }
    button:hover { opacity: 0.9; }
    section h2 { margin: 0 0 8px; font-size: 13px; font-weight: 600;
                 color: hsl(var(--muted-foreground)); text-transform: uppercase; letter-spacing: 0.05em; }
    .danger { color: hsl(0 72% 51%); }
    .toolbar { display: flex; gap: 8px; align-items: center; }
    .err { color: hsl(0 72% 51%); font-size: 12px; }
  </style>
</head>
<body>
  <div class="wrap" id="root">
    <div class="kpis">
      <div class="kpi"><h3>SKUs</h3><b id="kpi-skus">—</b></div>
      <div class="kpi"><h3>Units in stock</h3><b id="kpi-units">—</b></div>
      <div class="kpi warn"><h3>Low stock</h3><b id="kpi-low">—</b></div>
    </div>

    <section>
      <h2>Stock by SKU</h2>
      <div id="rows"></div>
    </section>

    <section>
      <h2>Quick actions</h2>
      <div class="toolbar">
        <button class="primary" id="btn-add">+ Add item</button>
        <button id="btn-refresh">Refresh</button>
        <span class="err" id="err"></span>
      </div>
    </section>
  </div>

  <script src="__bridge.js"></script>
  <script>
    (function () {
      var items = [];

      function $(id) { return document.getElementById(id); }
      function setErr(msg) { $("err").textContent = msg || ""; }

      function render() {
        var totalUnits = 0, low = 0;
        for (var i = 0; i < items.length; i++) {
          totalUnits += parseInt(items[i].quantity, 10) || 0;
          if (parseInt(items[i].quantity, 10) <= parseInt(items[i].reorder_level, 10)) low++;
        }
        $("kpi-skus").textContent  = items.length;
        $("kpi-units").textContent = totalUnits;
        $("kpi-low").textContent   = low;

        var html = "";
        for (var j = 0; j < items.length; j++) {
          var it = items[j];
          var qty = parseInt(it.quantity, 10) || 0;
          var isLow = qty <= (parseInt(it.reorder_level, 10) || 0);
          html += '<div class="row">'
            + '<div class="name">' + escape(it.sku) + ' · ' + escape(it.name) + '</div>'
            + '<div class="qty' + (isLow ? ' danger' : '') + '">' + qty + '</div>'
            + '<div class="actions">'
            +   '<button data-sku="' + escape(it.sku) + '" data-delta="-1">−</button>'
            +   '<button data-sku="' + escape(it.sku) + '" data-delta="1">+</button>'
            + '</div>'
            + '</div>';
        }
        $("rows").innerHTML = html;

        AtriaDash.setBadge(low > 0 ? {count: low, severity: "warning"} : null);
      }

      function escape(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
          return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c];
        });
      }

      async function refresh() {
        setErr("");
        try {
          var data = await AtriaDash.json("inventory.py", ["list", "--json"]);
          items = data.items || [];
          render();
        } catch (e) {
          setErr(e.message || "failed to load");
        }
      }

      $("rows").addEventListener("click", async function (ev) {
        var btn = ev.target.closest("button[data-sku]");
        if (!btn) return;
        var sku = btn.getAttribute("data-sku");
        var delta = btn.getAttribute("data-delta");
        btn.disabled = true;
        try {
          await AtriaDash.run("inventory.py",
            ["adjust", "--sku", sku, "--delta", delta]);
          refresh();
        } catch (e) {
          setErr(e.message || "adjust failed");
        } finally {
          btn.disabled = false;
        }
      });

      $("btn-add").addEventListener("click", function () {
        AtriaDash.openBlock("item_form", {mode: "create"});
      });
      $("btn-refresh").addEventListener("click", refresh);

      AtriaDash.onChange(refresh);
      AtriaDash.onContext(refresh);
      AtriaDash.ready();
    })();
  </script>
</body>
</html>
```

- [ ] **Step 3: Manual smoke**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run python -c "from pathlib import Path; p = Path('modules/warehouse/dashboard.html'); print('ok' if p.is_file() and len(p.read_text()) > 1000 else 'missing')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add modules/warehouse/dashboard.html modules/warehouse/icon.svg
git commit -m "feat(warehouse): dashboard.html + icon.svg

KPIs, per-SKU stepper rows that call inventory.py adjust, +Add item
opens item_form block via openBlock. Refreshes on AtriaDash.onChange."
```

---

## Task 8: Module — Migrate `item_form.html` to the new URL space

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/blocks/item_form.html`

- [ ] **Step 1: Rewrite the two reference URLs**

In `/Users/anlnm/Desktop/Project/opendev-py/modules/warehouse/blocks/item_form.html`, change:

```html
<link rel="stylesheet" href="/static/blocks/_base.css" />
```

to

```html
<link rel="stylesheet" href="../__base.css" />
```

and

```html
<script src="/static/blocks/_base.js"></script>
```

to

```html
<script src="../__bridge.js"></script>
```

(The relative URLs resolve to `/api/modules/warehouse/__base.css` and
`/api/modules/warehouse/__bridge.js` because the block itself is served from
`/api/modules/warehouse/blocks/item_form.html`.)

- [ ] **Step 2: Smoke-test that the file still parses + references the new paths**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && grep -nE "__base.css|__bridge.js" modules/warehouse/blocks/item_form.html`
Expected: two matches; no references to `/static/blocks/`.

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && ! grep -nE "/static/blocks/" modules/warehouse/blocks/item_form.html`
Expected: exit 0 (no matches found).

- [ ] **Step 3: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add modules/warehouse/blocks/item_form.html
git commit -m "refactor(warehouse): block uses per-module bridge URLs

Drops /static/blocks/_base.{css,js} in favour of relative
__base.css / __bridge.js served by the new module_dashboard router."
```

---

## Task 9: Frontend — `useModulesStore`

**Files:**
- Create: `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/stores/modules.ts`

- [ ] **Step 1: Create the store**

Create `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/stores/modules.ts`:

```typescript
import { create } from 'zustand';
import { apiClient } from '../api/client';
import { wsClient } from '../api/websocket';

export type BadgeSeverity = 'info' | 'warning' | 'danger';

export interface ModuleBadge {
  count: number;
  severity: BadgeSeverity;
}

interface ModuleSummary {
  name: string;
  has_icon: boolean;
}

interface ModulesState {
  modulesWithDashboards: ModuleSummary[];
  activeModuleDashboard: string | null;
  badges: Record<string, ModuleBadge | null>;
  refresh: () => Promise<void>;
  openDashboard: (name: string) => void;
  closeDashboard: () => void;
  setBadge: (module: string, badge: ModuleBadge | null) => void;
}

async function fetchModules(): Promise<ModuleSummary[]> {
  const res = await apiClient.get<Array<{name: string; files: string[]}>>(
    '/api/modules?has_dashboard=1'
  );
  return res.map(m => ({
    name: m.name,
    has_icon: m.files.includes('icon.svg'),
  }));
}

export const useModulesStore = create<ModulesState>((set, get) => ({
  modulesWithDashboards: [],
  activeModuleDashboard: null,
  badges: {},

  refresh: async () => {
    try {
      const mods = await fetchModules();
      set(state => {
        // If the currently active dashboard's module was removed, close it.
        const stillThere = state.activeModuleDashboard != null
          && mods.some(m => m.name === state.activeModuleDashboard);
        return {
          modulesWithDashboards: mods,
          activeModuleDashboard: stillThere ? state.activeModuleDashboard : null,
        };
      });
    } catch (e) {
      console.warn('failed to refresh modules', e);
    }
  },

  openDashboard: (name) => {
    const exists = get().modulesWithDashboards.some(m => m.name === name);
    if (!exists) return;
    set({ activeModuleDashboard: name });
  },

  closeDashboard: () => set({ activeModuleDashboard: null }),

  setBadge: (module, badge) =>
    set(state => ({ badges: { ...state.badges, [module]: badge } })),
}));

// Refresh on WS modules.changed (a new dashboard.html could appear).
wsClient.on('modules.changed', () => {
  useModulesStore.getState().refresh();
});

// Initial load.
useModulesStore.getState().refresh();
```

- [ ] **Step 2: Confirm `apiClient.get` returns parsed JSON in this codebase**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && grep -n "async get\|apiClient.get" web-ui/src/api/client.ts | head -5`
Expected: a `get<T>(url): Promise<T>` signature exists. If `apiClient` uses a different name (e.g. `apiGet`), adjust the import + call site to match. **Do not skip this verification.** The store will silently no-op on a mismatch.

- [ ] **Step 3: TypeScript-check**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && cd web-ui && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add web-ui/src/stores/modules.ts
git commit -m "feat(web-ui): useModulesStore for dashboard buttons + badges

Loads modules with dashboard.html, tracks active dashboard + per-module
sidebar badges. Refreshes on ws modules.changed."
```

---

## Task 10: Frontend — `ProjectSidebar` Modules group

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/Layout/ProjectSidebar.tsx`

- [ ] **Step 1: Add imports + state hookups near the top of `ProjectSidebar`**

In `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/Layout/ProjectSidebar.tsx`:

A) Add to the lucide-react imports list: `Package`.
B) Add an import after the existing store imports:

```typescript
import { useModulesStore } from '../../stores/modules';
```

C) Inside the component body (right after the other store-hook lines such as `const isCollapsed = useChatStore(s => s.sidebarCollapsed)`), add:

```typescript
const modulesWithDashboards = useModulesStore(s => s.modulesWithDashboards);
const activeModuleDashboard = useModulesStore(s => s.activeModuleDashboard);
const moduleBadges = useModulesStore(s => s.badges);
const openModuleDashboard = useModulesStore(s => s.openDashboard);
const closeModuleDashboard = useModulesStore(s => s.closeDashboard);
```

- [ ] **Step 2: Render the Modules group at the bottom of the expanded sidebar**

Find the closing `</div>` of the scrollable inner region (the `flex-1 overflow-y-auto py-1` block) and immediately before it add:

```tsx
{modulesWithDashboards.length > 0 && (
  <div className="border-t border-border-300/10 mt-2 pt-2">
    <div className="px-3 pb-1 text-[10px] font-mono uppercase tracking-wider text-text-500">
      Modules
    </div>
    {modulesWithDashboards.map(m => {
      const isActive = activeModuleDashboard === m.name;
      const badge = moduleBadges[m.name] || null;
      const iconUrl = m.has_icon ? `/api/modules/${m.name}/icon.svg` : null;
      return (
        <button
          key={m.name}
          onClick={() => {
            if (isActive) closeModuleDashboard();
            else openModuleDashboard(m.name);
          }}
          className={`group flex items-center gap-2 px-3 py-1.5 w-full transition-colors text-left ${
            isActive
              ? 'bg-accent-main-100/10 border-r-2 border-accent-main-100'
              : 'hover:bg-bg-200/40'
          }`}
        >
          {iconUrl
            ? <img src={iconUrl} className="w-3.5 h-3.5 flex-shrink-0" alt="" />
            : <Package className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? 'text-accent-main-100' : 'text-text-400'}`} />}
          <span className={`flex-1 text-xs truncate ${isActive ? 'text-accent-main-100 font-medium' : 'text-text-200'}`}>
            {m.name}
          </span>
          {badge && (
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                badge.severity === 'danger'  ? 'bg-semantic-danger' :
                badge.severity === 'warning' ? 'bg-amber-400'       :
                                               'bg-accent-main-100'
              }`}
              title={`${badge.count}`}
            />
          )}
        </button>
      );
    })}
  </div>
)}
```

- [ ] **Step 3: Add a collapsed-rail icon for each module in the `isCollapsed` branch**

Above the existing `<aside data-surface="dark" className="w-12 …">` returned in the collapsed branch (around line 60), keep the existing collapse/new-project buttons, and below them add:

```tsx
{modulesWithDashboards.map(m => {
  const isActive = activeModuleDashboard === m.name;
  const badge = moduleBadges[m.name] || null;
  return (
    <button
      key={m.name}
      onClick={() => {
        if (isActive) closeModuleDashboard();
        else openModuleDashboard(m.name);
      }}
      className={`relative p-1.5 rounded transition-colors ${
        isActive ? 'bg-accent-main-100/10 text-accent-main-100'
                 : 'hover:bg-bg-200 text-text-400 hover:text-text-200'
      }`}
      title={m.name}
    >
      {m.has_icon
        ? <img src={`/api/modules/${m.name}/icon.svg`} className="w-4 h-4" alt="" />
        : <Package className="w-4 h-4" />}
      {badge && (
        <span
          className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${
            badge.severity === 'danger'  ? 'bg-semantic-danger' :
            badge.severity === 'warning' ? 'bg-amber-400'       :
                                           'bg-accent-main-100'
          }`}
        />
      )}
    </button>
  );
})}
```

(Inserted directly inside the existing `<aside>` after the New Project button, before the closing `</aside>`.)

- [ ] **Step 4: TypeScript-check + smoke-render**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py/web-ui && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add web-ui/src/components/Layout/ProjectSidebar.tsx
git commit -m "feat(web-ui): Modules group in ProjectSidebar

One button per module with dashboard.html. Active highlight,
optional icon.svg, badge dot driven by useModulesStore.
Mirrored in the collapsed rail."
```

---

## Task 11: Frontend — `ModuleDashboardView` + `useModuleBridge` hook

**Files:**
- Create: `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/ModuleDashboard/ModuleDashboardView.tsx`
- Create: `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/ModuleDashboard/useModuleBridge.ts`

- [ ] **Step 1: Create the bridge hook**

Create `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/ModuleDashboard/useModuleBridge.ts`:

```typescript
import { useEffect, useRef } from 'react';
import { apiClient } from '../../api/client';
import { wsClient } from '../../api/websocket';
import { useModulesStore } from '../../stores/modules';
import { useToastStore } from '../../stores/toast';

interface RunBody {
  script: string;
  args: string[];
  stdin?: string;
  timeout_ms?: number;
}

interface RunResult {
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms: number;
}

interface UseModuleBridgeOpts {
  moduleName: string;
  sessionId: string | null;
  iframeRef: React.RefObject<HTMLIFrameElement>;
  visible: boolean;
}

export function useModuleBridge({ moduleName, sessionId, iframeRef, visible }: UseModuleBridgeOpts) {
  const setBadge = useModulesStore(s => s.setBadge);
  const closeDashboard = useModulesStore(s => s.closeDashboard);
  const pushToast = useToastStore(s => s.push);
  const readyRef = useRef(false);

  // Post a typed message into the iframe.
  function postToIframe(msg: any) {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    win.postMessage(msg, '*');
  }

  // Send context (sessionId, moduleName) once ready.
  useEffect(() => {
    if (!readyRef.current || !sessionId) return;
    postToIframe({
      type: 'context',
      sessionId,
      moduleName,
      moduleRoot: `/api/modules/${moduleName}`,
    });
  }, [moduleName, sessionId]);

  // Visibility ping when the user toggles between chat and dashboard.
  useEffect(() => {
    if (!readyRef.current) return;
    postToIframe({ type: 'visibility', visible });
  }, [visible]);

  // Handle inbound messages from the iframe.
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      const win = iframeRef.current?.contentWindow;
      if (!win || ev.source !== win) return;
      const msg = ev.data;
      if (!msg || typeof msg.type !== 'string') return;

      switch (msg.type) {
        case 'ready':
          readyRef.current = true;
          if (sessionId) {
            postToIframe({
              type: 'context',
              sessionId,
              moduleName,
              moduleRoot: `/api/modules/${moduleName}`,
            });
          }
          postToIframe({ type: 'visibility', visible });
          return;

        case 'badge':
          setBadge(moduleName, msg.value || null);
          return;

        case 'title':
          // Currently surfaced via the view's own header (reads through msg.text
          // if the view subscribes — implemented in the view component below).
          window.dispatchEvent(new CustomEvent('atria:module:title', {
            detail: { module: moduleName, text: String(msg.text || '') },
          }));
          return;

        case 'toast':
          pushToast({
            message: String(msg.message || ''),
            severity: msg.severity || 'info',
          });
          return;

        case 'openBlock': {
          if (!sessionId) return;
          // Reuse the existing push_block HTTP gateway.
          apiClient.post('/api/blocks/push', {
            session_id: sessionId,
            module: moduleName,
            block: String(msg.block || ''),
            props: msg.props || {},
            title: null,
          }).catch(e => pushToast({ message: `openBlock failed: ${e.message}`, severity: 'danger' }));
          return;
        }

        case 'openChat':
          closeDashboard();
          return;

        case 'run': {
          const body: RunBody = {
            script: String(msg.script || ''),
            args: Array.isArray(msg.args) ? msg.args.map(String) : [],
          };
          if (msg.stdin != null) body.stdin = String(msg.stdin);
          if (msg.timeout_ms) body.timeout_ms = Number(msg.timeout_ms);
          apiClient.post<RunResult>(`/api/modules/${moduleName}/run`, body).then(result => {
            postToIframe({ type: 'run:result', requestId: msg.requestId, ...result });
          }).catch(err => {
            const detail = err?.body?.detail || {};
            postToIframe({
              type: 'run:error',
              requestId: msg.requestId,
              kind: detail.kind || 'spawn-failed',
              message: detail.message || err.message || 'run failed',
            });
          });
          return;
        }
      }
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [moduleName, sessionId, visible, setBadge, closeDashboard, pushToast, iframeRef]);

  // Forward WS modules.changed events into the iframe.
  useEffect(() => {
    function onChanged(payload: any) {
      if (!payload || (payload.name && payload.name !== moduleName && payload.name !== '*')) return;
      postToIframe({ type: 'change', paths: [] });
    }
    wsClient.on('modules.changed', onChanged);
    return () => { (wsClient as any).off?.('modules.changed', onChanged); };
  }, [moduleName]);
}
```

- [ ] **Step 2: Create the view**

Create `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/components/ModuleDashboard/ModuleDashboardView.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, RotateCw } from 'lucide-react';
import { useChatStore } from '../../stores/chat';
import { useModulesStore } from '../../stores/modules';
import { useModuleBridge } from './useModuleBridge';

interface Props {
  moduleName: string;
}

export function ModuleDashboardView({ moduleName }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sessionId = useChatStore(s => s.currentSessionId);
  const closeDashboard = useModulesStore(s => s.closeDashboard);
  const [title, setTitle] = useState<string | null>(null);

  useModuleBridge({ moduleName, sessionId, iframeRef, visible: true });

  // Listen for AtriaDash.setTitle messages dispatched as a window event.
  useEffect(() => {
    function onTitle(ev: Event) {
      const detail = (ev as CustomEvent).detail;
      if (detail?.module === moduleName) setTitle(detail.text || null);
    }
    window.addEventListener('atria:module:title', onTitle);
    return () => window.removeEventListener('atria:module:title', onTitle);
  }, [moduleName]);

  function refresh() {
    const f = iframeRef.current;
    if (!f) return;
    // Hard refresh: re-set src to bust any iframe-side state. Cheapest reliable
    // mechanism without piping a refresh-message through the bridge protocol.
    f.src = f.src;
  }

  return (
    <div className="flex-1 flex flex-col bg-bg-000 min-h-0">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border-300/15 bg-bg-100">
        <button
          onClick={closeDashboard}
          className="flex items-center gap-1 text-xs text-text-300 hover:text-text-100 transition-colors"
          title="Back to chat"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to chat
        </button>
        <span className="text-xs text-text-500">·</span>
        <span className="text-xs font-medium text-text-200">
          {title || `${moduleName} · dashboard`}
        </span>
        <div className="flex-1" />
        <button
          onClick={refresh}
          className="p-1 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
          title="Refresh"
        >
          <RotateCw className="w-3.5 h-3.5" />
        </button>
      </div>
      <iframe
        ref={iframeRef}
        src={`/api/modules/${moduleName}/dashboard.html`}
        sandbox="allow-scripts"
        className="flex-1 border-0 bg-bg-000"
        title={`${moduleName} dashboard`}
      />
    </div>
  );
}
```

- [ ] **Step 3: Verify `apiClient.post` shape**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && grep -n "async post\|apiClient.post" web-ui/src/api/client.ts | head -5`
Expected: a `post<T>(url, body): Promise<T>` exists. If it differs, adjust call sites. Confirm `useToastStore.push` exists with `{message, severity}` shape; if it differs, adjust.

- [ ] **Step 4: TypeScript-check**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py/web-ui && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add web-ui/src/components/ModuleDashboard/
git commit -m "feat(web-ui): ModuleDashboardView + useModuleBridge

Iframe with sandbox=allow-scripts loads /api/modules/<name>/dashboard.html.
Bridge handles run/badge/title/toast/openBlock/openChat and forwards
ws modules.changed events as iframe 'change' messages."
```

---

## Task 12: Frontend — Route swap in `ChatPage`

**Files:**
- Modify: `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/pages/ChatPage.tsx`

- [ ] **Step 1: Read the file to find the `<main>` wrapper**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && cat web-ui/src/pages/ChatPage.tsx`
Note: identify where `<ChatView>` (or its inline equivalent) is rendered inside `<main>`.

- [ ] **Step 2: Swap the main content based on `activeModuleDashboard`**

In `/Users/anlnm/Desktop/Project/opendev-py/web-ui/src/pages/ChatPage.tsx`:

A) Add imports:

```typescript
import { useModulesStore } from '../stores/modules';
import { ModuleDashboardView } from '../components/ModuleDashboard/ModuleDashboardView';
```

B) Inside the component body, before the return:

```typescript
const activeModuleDashboard = useModulesStore(s => s.activeModuleDashboard);
```

C) Replace the existing main content. The current shape is roughly:

```tsx
<main className="flex-1 flex flex-col overflow-hidden bg-bg-000">
  {/* …existing chat children… */}
</main>
```

Change to:

```tsx
<main className="flex-1 flex flex-col overflow-hidden bg-bg-000">
  {activeModuleDashboard
    ? <ModuleDashboardView moduleName={activeModuleDashboard} />
    : (
      <>
        {/* …existing chat children verbatim… */}
      </>
    )}
</main>
```

(Keep every existing child element inside the `<>…</>` fragment exactly as it was.)

- [ ] **Step 3: TypeScript-check + manual smoke**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py/web-ui && npx tsc --noEmit`
Expected: clean.

Manual smoke:

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
make build-ui
export OPENAI_API_KEY=<key>
atria run ui &
# In the browser:
# 1. Sidebar shows "warehouse" under "Modules".
# 2. Click warehouse → main area swaps to the dashboard.
# 3. KPIs render: 3 SKUs, 65 units, 1 low.
# 4. Click "−" on Sprocket → quantity decrements, low badge updates.
# 5. Click "+ Add item" → item_form block opens in chat (return to chat
#    via the back button).
# 6. Edit modules/warehouse/dashboard.html on disk → iframe refresh icon
#    works; watcher refires modules.changed.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git add web-ui/src/pages/ChatPage.tsx
git commit -m "feat(web-ui): ChatPage swaps main area to dashboard when active

Reads useModulesStore.activeModuleDashboard. ChatView and
ModuleDashboardView are mutually exclusive; clicking a module button
or closing the dashboard switches between them."
```

---

## Task 13: End-to-end verification + spec close-out

**Files:** none

- [ ] **Step 1: Backend suite green**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && uv run pytest tests/test_module_dashboard_routes.py tests/test_modules_routes.py tests/test_warehouse_inventory.py -v`
Expected: all green.

- [ ] **Step 2: TS green**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py/web-ui && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Lint + format gates**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && make lint typecheck`
Expected: clean.

- [ ] **Step 4: Real e2e — full warehouse loop in the running UI**

Run: `cd /Users/anlnm/Desktop/Project/opendev-py && make build-ui && OPENAI_API_KEY=<key> atria run ui`
In the browser:
- Open a chat; sidebar shows the `warehouse` button (icon + name).
- Click button → dashboard loads, shows 3 KPIs.
- Click `−` on Sprocket twice → row shows `1`, badge severity stays warning.
- Click `+ Add item` → form opens in the chat. Submit a new SKU → CSV updates;
  the dashboard's `onChange` fires; KPI counts increase by 1; badge updates.
- Click back-to-chat header → returns to the conversation. Click warehouse
  button again → dashboard re-renders with retained state (iframe not
  remounted while in the same session).

- [ ] **Step 5: Final commit (none expected) + tag the plan as complete**

```bash
cd /Users/anlnm/Desktop/Project/opendev-py
git status   # should be clean
git log --oneline -n 14
```

Expected: 12+ commits, one per task, latest is the routing swap.

---

## Self-Review Notes

- Every spec section has a backing task:
  - URL surface → Tasks 1–3, 5.
  - WebSocket integration → reuses existing `modules.changed`; routed by
    `useModuleBridge` (Task 11).
  - Sidebar buttons → Task 10.
  - Main-area swap → Task 12.
  - AtriaDash JS API → Task 2 (bridge content).
  - Platform vendor tier → Task 2 directory structure; the actual
    Chart.js/htmx binaries are dropped into
    `atria/web/dashboard_assets/vendor/chartjs@4/` and `htmx@2/` at the
    end of Task 2 (download from the official CDN onto disk as part of
    the same commit; **do not** wire them up as network fetches at
    runtime). The warehouse dashboard in this v1 doesn't use them — but
    they're available for any future module without further plumbing.
  - Block migration → Task 8.
  - Concrete warehouse use → Tasks 6, 7, 8.
- Type/method consistency: `AtriaDash.run` and the route both use
  `{exit_code, stdout, stderr, duration_ms}` plus `{kind, message}` on
  errors. Wire types in `useModuleBridge` match.
- No `TBD`/`TODO`/"add validation" placeholders.
- One scope thing worth calling out before execution: Task 2's vendor
  binaries (Chart.js + htmx) are *not* yet shipped as committed files in
  this repo. If you don't want to commit those binaries to git, defer
  the `vendor/` dir creation; the routes don't break — only an attempt
  to GET them returns 404. The warehouse dashboard does **not** depend
  on them, so deferring is safe.
