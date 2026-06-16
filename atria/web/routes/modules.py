"""REST API for file-based modules.

A module is a folder under ``<root>/<name>/`` containing at minimum ``SKILL.md``.
Per-file editing of arbitrary contents (e.g. ``scripts/foo.py``,
``templates/dash.html``) goes through the ``/fs/*`` sub-routes below.
"""

from __future__ import annotations

import mimetypes
from contextlib import contextmanager
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from atria.core.modules import store
from atria.core.modules.registry import ModuleRegistry
from atria.core.modules.store import (
    InvalidModuleName,
    ModuleExists,
    ModuleNotFound,
    Template,
)
from atria.web.dependencies import get_modules_registry


router = APIRouter(prefix="/api/modules", tags=["modules"])

_STREAM_CHUNK = 16 * 1024


class ModuleDashboardManifestOut(BaseModel):
    model_config = {"from_attributes": True}

    title: Optional[str] = None
    default_height: Optional[int] = None
    badge_color: Optional[str] = None


class ModuleManifestOut(BaseModel):
    model_config = {"from_attributes": True}

    display_name: Optional[str] = None
    tooltip: Optional[str] = None
    icon: Optional[str] = None
    dashboard: Optional[ModuleDashboardManifestOut] = None


class ModuleOut(BaseModel):
    model_config = {"from_attributes": True}

    name: str
    skill_md: str
    mtime: float
    files: List[str]
    manifest: Optional[ModuleManifestOut] = None


class ModuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template: Optional[Template] = "skill"
    summary: Optional[str] = ""


class FileWrite(BaseModel):
    path: str = Field(min_length=1)
    content: str


class PathBody(BaseModel):
    path: str = Field(min_length=1)


class RenameBody(BaseModel):
    model_config = {"populate_by_name": True}

    from_: str = Field(min_length=1, alias="from")
    to: str = Field(min_length=1)
    force: bool = False


@contextmanager
def _store_errors(name: str | None = None) -> Iterator[None]:
    """Map store exceptions to HTTPExceptions in one place.

    Pass the module ``name`` to get a nicer 404 message; omit for endpoints
    where the name isn't bound yet (e.g. create).
    """
    label = repr(name) if name is not None else "<unknown>"
    try:
        yield
    except InvalidModuleName as exc:
        raise HTTPException(400, str(exc)) from exc
    except ModuleNotFound as exc:
        raise HTTPException(404, f"module {label} not found") from exc
    except ModuleExists as exc:
        raise HTTPException(409, f"module {label} already exists") from exc
    except NotADirectoryError as exc:
        raise HTTPException(400, "not a directory") from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "file not found") from exc
    except FileExistsError as exc:
        raise HTTPException(409, "destination already exists") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("", response_model=List[ModuleOut])
def list_endpoint(
    has_dashboard: bool = Query(False),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    items = reg.all()
    if has_dashboard:
        items = [m for m in items if "dashboard.html" in m.files]
    return [ModuleOut.model_validate(m) for m in items]


@router.get("/{name}", response_model=ModuleOut)
def get_endpoint(name: str, reg: ModuleRegistry = Depends(get_modules_registry)):
    with _store_errors(name):
        return ModuleOut.model_validate(store.read_module(reg.root, name))


@router.post("", response_model=ModuleOut, status_code=201)
def create_endpoint(body: ModuleCreate, reg: ModuleRegistry = Depends(get_modules_registry)):
    with _store_errors(body.name):
        m = store.create_module(
            reg.root,
            body.name,
            template=body.template or "skill",
            summary=body.summary or "",
        )
    reg.reload_one(body.name)
    return ModuleOut.model_validate(m)


@router.delete("/{name}", status_code=204)
def delete_endpoint(name: str, reg: ModuleRegistry = Depends(get_modules_registry)):
    with _store_errors(name):
        store.delete_module(reg.root, name)
    reg.remove(name)
    return None


# ── Per-file fs sub-routes ─────────────────────────────────────────────────────


@router.get("/{name}/fs/list")
def fs_list(
    name: str,
    path: str = Query(""),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        entries = store.list_dir(reg.root, name, path)
    return {"path": path, "entries": entries}


@router.get("/{name}/fs/read")
def fs_read(
    name: str,
    path: str = Query(..., min_length=1),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        data = store.read_file(reg.root, name, path)

    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "application/octet-stream"

    def _iter() -> Iterator[bytes]:
        for i in range(0, len(data), _STREAM_CHUNK):
            yield data[i : i + _STREAM_CHUNK]

    return StreamingResponse(
        _iter(),
        media_type=mime,
        headers={"Cache-Control": "no-cache", "Content-Length": str(len(data))},
    )


@router.put("/{name}/fs/write", status_code=204)
def fs_write(
    name: str,
    body: FileWrite,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.write_file(reg.root, name, body.path, body.content)
    reg.reload_one(name)
    return None


@router.post("/{name}/fs/mkdir", status_code=204)
def fs_mkdir(
    name: str,
    body: PathBody,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.mkdir(reg.root, name, body.path)
    reg.reload_one(name)
    return None


@router.post("/{name}/fs/touch", status_code=204)
def fs_touch(
    name: str,
    body: PathBody,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.touch_file(reg.root, name, body.path)
    reg.reload_one(name)
    return None


@router.post("/{name}/fs/rename", status_code=204)
def fs_rename(
    name: str,
    body: RenameBody,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.rename_path(reg.root, name, body.from_, body.to, force=body.force)
    reg.reload_one(name)
    return None


@router.delete("/{name}/fs/file", status_code=204)
def fs_delete(
    name: str,
    path: str = Query(..., min_length=1),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.delete_file(reg.root, name, path)
    reg.reload_one(name)
    return None
