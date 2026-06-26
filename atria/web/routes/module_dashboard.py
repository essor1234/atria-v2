"""Module interactive dashboard routes.

Provides a subprocess gateway so a module's static dashboard (templates +
scripts) can invoke its own Python scripts via HTTP. Future tasks append
additional routes (artifact serving, websocket streams, etc.) to this same
router.
"""

from __future__ import annotations

import mimetypes
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from atria.core.modules import store as _store
from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import InvalidModuleName, ModuleNotFound
from atria.web.dependencies.modules import get_modules_registry

router = APIRouter(prefix="/api/modules", tags=["module-dashboard"])


# ── Concurrency tracking ──────────────────────────────────────────────────────

_MAX_INFLIGHT_PER_KEY = 4
_inflight_lock = threading.Lock()
_inflight: dict[tuple[str, str], int] = defaultdict(int)


def _try_acquire(session_id: str, module_name: str) -> bool:
    key = (session_id, module_name)
    with _inflight_lock:
        if _inflight[key] >= _MAX_INFLIGHT_PER_KEY:
            return False
        _inflight[key] += 1
        return True


def _release(session_id: str, module_name: str) -> None:
    key = (session_id, module_name)
    with _inflight_lock:
        if _inflight[key] > 0:
            _inflight[key] -= 1
        if _inflight[key] == 0:
            _inflight.pop(key, None)


# ── Request / response models ─────────────────────────────────────────────────


class RunBody(BaseModel):
    script: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    stdin: str | None = None
    timeout_ms: int = Field(default=30000, ge=1, le=120000)


class RunResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve_session_id(request: Request) -> str:
    sid = request.cookies.get("session_id")
    if sid:
        return sid
    sid = request.headers.get("x-atria-session-id")
    if sid:
        return sid
    return "default"


def _resolve_script(module_dir: Path, script: str) -> Path:
    # Reject absolute paths up front.
    if script.startswith("/") or Path(script).is_absolute():
        raise HTTPException(
            status_code=400,
            detail={"kind": "path-escape", "message": f"absolute paths not allowed: {script!r}"},
        )
    scripts_dir = (module_dir / "scripts").resolve()
    candidate = (scripts_dir / script).resolve()
    try:
        candidate.relative_to(scripts_dir)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "kind": "path-escape",
                "message": f"script path escapes scripts/: {script!r}",
            },
        ) from None
    return candidate


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/{name}/run", response_model=RunResponse)
def run_script(
    name: str,
    body: RunBody,
    request: Request,
    reg: ModuleRegistry = Depends(get_modules_registry),
) -> RunResponse:
    try:
        module = reg.get(name)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"kind": "unknown-module", "message": f"module {name!r} not found"},
        ) from None

    module_dir = module.dir.resolve()
    root_resolved = reg.root.resolve()
    try:
        module_dir.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail={"kind": "unknown-module", "message": f"module {name!r} not found"},
        ) from None
    if not module_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"kind": "unknown-module", "message": f"module {name!r} not found"},
        )

    target = _resolve_script(module_dir, body.script)
    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "kind": "unknown-script",
                "message": f"script {body.script!r} not found in module {name!r}",
            },
        )

    session_id = _resolve_session_id(request)
    if not _try_acquire(session_id, name):
        raise HTTPException(
            status_code=429,
            detail={
                "kind": "rate-limited",
                "message": (
                    f"too many in-flight runs for session/module " f"(max {_MAX_INFLIGHT_PER_KEY})"
                ),
            },
        )

    try:
        env = os.environ.copy()
        env["ATRIA_SESSION_ID"] = session_id
        env["ATRIA_MODULE_ROOT"] = str(module_dir)
        env.setdefault("ATRIA_API_BASE", "http://127.0.0.1:8000")

        cmd = [sys.executable, str(target), *body.args]
        timeout_s = body.timeout_ms / 1000.0
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=body.stdin,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                cwd=str(module_dir),
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            return RunResponse(
                exit_code=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = (
                e.stdout if isinstance(e.stdout, str) else (e.stdout.decode() if e.stdout else "")
            )
            stderr = (
                e.stderr if isinstance(e.stderr, str) else (e.stderr.decode() if e.stderr else "")
            )
            stderr = (stderr or "") + f"\n[atria] script timeout after {body.timeout_ms} ms"
            return RunResponse(
                exit_code=-1,
                stdout=stdout or "",
                stderr=stderr,
                duration_ms=duration_ms,
            )
    finally:
        _release(session_id, name)


# ── Virtual platform assets ─────────────────────────────────────────────────

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "dashboard_assets"

_VIRTUAL_MIME = {
    "__bridge.js": "application/javascript; charset=utf-8",
    "__base.css": "text/css; charset=utf-8",
}


def _err(status: int, kind: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"kind": kind, "message": message})


def _serve_asset(rel: str, mime: str) -> Response:
    p = (_ASSETS_DIR / rel).resolve()
    try:
        p.relative_to(_ASSETS_DIR)
    except ValueError:
        raise _err(404, "not-found", "asset not found") from None
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
    rel = f"vendor/{lib}/{filename}"
    mime, _ = mimetypes.guess_type(filename)
    if mime is None:
        mime = "application/octet-stream"
    return _serve_asset(rel, mime)


# ── Module-owned physical files ─────────────────────────────────────────────


def _serve_module_file(reg: ModuleRegistry, name: str, rel: str) -> Response:
    try:
        data = _store.read_file(reg.root, name, rel)
    except InvalidModuleName as exc:
        raise _err(400, "invalid-module-name", str(exc)) from None
    except ModuleNotFound:
        raise _err(404, "unknown-module", f"module {name!r} not found") from None
    except FileNotFoundError:
        raise _err(404, "not-found", "file not found") from None
    except ValueError as exc:
        raise _err(400, "path-escape", str(exc)) from None
    mime, _ = mimetypes.guess_type(rel)
    if mime is None:
        mime = "application/octet-stream"
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


@router.get("/{name}/dashboard.html")
def serve_dashboard_html(
    name: str, reg: ModuleRegistry = Depends(get_modules_registry)
) -> Response:
    return _serve_module_file(reg, name, "dashboard.html")


@router.get("/{name}/icon.svg")
def serve_icon_svg(name: str, reg: ModuleRegistry = Depends(get_modules_registry)) -> Response:
    return _serve_module_file(reg, name, "icon.svg")


@router.get("/{name}/blocks/{filename:path}")
def serve_block_file(
    name: str, filename: str, reg: ModuleRegistry = Depends(get_modules_registry)
) -> Response:
    return _serve_module_file(reg, name, f"blocks/{filename}")


@router.get("/{name}/vendor/{filename:path}")
def serve_module_vendor(
    name: str, filename: str, reg: ModuleRegistry = Depends(get_modules_registry)
) -> Response:
    return _serve_module_file(reg, name, f"vendor/{filename}")
