"""REST API for file-based modules.

A module is a folder under ``<root>/<name>/`` containing at minimum ``SKILL.md``.
Per-file editing of arbitrary contents (e.g. ``scripts/foo.py``,
``templates/dash.html``) goes through the ``/fs/*`` sub-routes below.
"""

from __future__ import annotations

import mimetypes
from contextlib import contextmanager
from typing import Iterator, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
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
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB per file, matching artifact uploads


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
    description: str = ""
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


@router.post("/{name}/data/upload")
async def data_upload_endpoint(
    name: str,
    files: List[UploadFile] = File(...),
    rel_paths: List[str] = Form(default=[]),
    convert_xlsx: bool = Form(True),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    """Upload data files/folders into a module's data/ dir.

    ``rel_paths`` is a parallel array to ``files`` carrying each file's
    folder-relative path (e.g. from a webkitdirectory pick); when absent the
    bare filename is used. Excel files are also converted to CSV when
    ``convert_xlsx`` is set. SKILL.md is regenerated to describe the datasets.
    """
    plan: list[tuple[str, bytes]] = []
    converted: list[str] = []
    skipped: list[dict] = []

    for i, uf in enumerate(files):
        data = await uf.read()
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{uf.filename!r} exceeds the {_MAX_UPLOAD_BYTES} byte limit")
        rel = (rel_paths[i] if i < len(rel_paths) and rel_paths[i] else None) or uf.filename or f"file_{i}"
        plan.append((rel, data))

        if convert_xlsx and rel.lower().endswith((".xlsx", ".xlsm")):
            try:
                from atria.core.modules.xlsx_convert import xlsx_to_csvs

                head, _, tail = rel.replace("\\", "/").rpartition("/")
                folder = f"{head}/" if head else ""
                stem = tail.rsplit(".", 1)[0]
                for fname, cdata in xlsx_to_csvs(data, stem):
                    plan.append((f"{folder}{fname}", cdata))
                    converted.append(f"{folder}{fname}")
            except Exception as exc:  # noqa: BLE001 — convert failure shouldn't abort the upload
                skipped.append({"file": rel, "error": f"xlsx conversion failed: {exc}"})

    with _store_errors(name):
        written = store.write_data_files(reg.root, name, plan)
        store.regenerate_data_skill(reg.root, name)
    reg.reload_one(name)
    return {"written": written, "converted": converted, "skipped": skipped}


@router.get("/{name}/data/read")
def data_read_endpoint(
    name: str,
    file: str = Query(..., min_length=1),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    """Read a module CSV dataset as ``{file, columns, rows}`` (for the editable grid)."""
    with _store_errors(name):
        return store.read_dataset(reg.root, name, file)


class DatasetWrite(BaseModel):
    file: str = Field(..., min_length=1)
    columns: list = Field(default_factory=list)
    rows: list = Field(default_factory=list)


@router.put("/{name}/data/write")
def data_write_endpoint(
    name: str,
    body: DatasetWrite,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    """Write edited rows back to a module CSV dataset, then refresh the module.

    Validation/containment failures surface as 4xx JSON (never a 500) via
    ``_store_errors``; the CSV is replaced atomically with a single ``.bak``.
    """
    with _store_errors(name):
        result = store.write_dataset(reg.root, name, body.file, body.columns, body.rows)
        # Only refresh the auto-generated SKILL.md for generic data-template
        # modules (which own scripts/data.py). Custom modules (e.g. warehouse,
        # with their own scripts) keep their hand-authored SKILL.md untouched.
        if (reg.root / name / "scripts" / "data.py").is_file():
            store.regenerate_data_skill(reg.root, name)
    reg.reload_one(name)
    return {"ok": True, **result}


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

    filename = path.rsplit("/", 1)[-1] or "file"
    return StreamingResponse(
        _iter(),
        media_type=mime,
        headers={
            "Cache-Control": "no-cache",
            "Content-Length": str(len(data)),
            "Content-Disposition": f'inline; filename="{filename}"',
        },
    )


async def _broadcast_artifact_changed(payload: dict) -> None:
    """Best-effort fire-and-forget broadcast.

    The shared ``broadcast_to_all_clients`` depends on global app state that
    isn't always initialized (e.g. lightweight unit tests). Failures here must
    never break the write path, so we swallow everything.
    """
    try:
        from atria.web.state import broadcast_to_all_clients

        await broadcast_to_all_clients(payload)
    except Exception:
        pass


@router.put("/{name}/fs/write", status_code=204)
async def fs_write(
    name: str,
    body: FileWrite,
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    with _store_errors(name):
        store.write_file(reg.root, name, body.path, body.content)
    reg.reload_one(name)
    await _broadcast_artifact_changed(
        {
            "type": "artifact.changed",
            "scope": "module",
            "module": name,
            "path": body.path,
        }
    )
    return None


_MAX_MODULE_WRITE_BYTES: int = 25 * 1024 * 1024


@router.put("/{name}/fs/write-binary", status_code=204)
async def fs_write_binary(
    name: str,
    request: Request,
    path: str = Query(..., min_length=1),
    reg: ModuleRegistry = Depends(get_modules_registry),
):
    """Write raw bytes to a file inside the module.

    Body is ``application/octet-stream``. Path lives in the query string.
    Broadcasts ``artifact.changed`` on success.
    """
    data = await request.body()
    if len(data) > _MAX_MODULE_WRITE_BYTES:
        raise HTTPException(status_code=413, detail="content too large")
    with _store_errors(name):
        store.write_file_bytes(reg.root, name, path, data)
    reg.reload_one(name)
    await _broadcast_artifact_changed(
        {
            "type": "artifact.changed",
            "scope": "module",
            "module": name,
            "path": path,
        }
    )
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
