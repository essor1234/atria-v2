"""Filesystem browsing endpoints scoped to a conversation's working directory."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from atria.db.connection import get_sessionmaker
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.web.dependencies.auth import require_authenticated_user

router = APIRouter(
    prefix="/api/conversations",
    tags=["fs"],
    dependencies=[Depends(require_authenticated_user)],
)

_DEFAULT_IGNORE: frozenset[str] = frozenset(
    {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
)
_MAX_READ_BYTES: int = 25 * 1024 * 1024  # 25 MB


def _resolve_safe(base: Path, user_path: str) -> Path:
    if user_path.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail="absolute path not allowed")
    base_resolved = base.resolve(strict=True)
    target = (base_resolved / user_path).resolve(strict=False)
    try:
        target.relative_to(base_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside workspace") from exc
    return target


async def _conv_working_dir(conversation_id: int) -> Path:
    sm = await get_sessionmaker()
    repo = ConversationRepository(sm)
    conv = await repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    wd = conv["working_directory"]
    if not wd or not os.path.isdir(wd):
        raise HTTPException(status_code=404, detail="Working directory missing")
    return Path(wd)


@router.get("/{conversation_id}/fs/list")
async def list_dir(
    conversation_id: int,
    path: str = Query(""),
    show_hidden: bool = Query(False),
) -> dict:
    base = await _conv_working_dir(conversation_id)
    target = _resolve_safe(base, path)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    entries: list[dict] = []
    for child in target.iterdir():
        name = child.name
        _always_visible = {".artifacts"}
        if not show_hidden and name.startswith(".") and name not in _always_visible:
            continue
        if name in _DEFAULT_IGNORE:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        entries.append(
            {
                "name": name,
                "kind": "dir" if is_dir else "file",
                "size": 0 if is_dir else stat.st_size,
                "mtime": stat.st_mtime,
                "ext": "" if is_dir else child.suffix.lower(),
            }
        )

    entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
    return {"path": path, "entries": entries}


@router.get("/{conversation_id}/fs/read")
async def read_file(
    conversation_id: int,
    path: str = Query(..., min_length=1),
) -> StreamingResponse:
    base = await _conv_working_dir(conversation_id)
    target = _resolve_safe(base, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="file not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="not a file")

    try:
        size = target.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=404, detail="file not found") from exc
    if size > _MAX_READ_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"message": "file too large", "size": size, "limit": _MAX_READ_BYTES},
        )

    mime, _ = mimetypes.guess_type(str(target))
    if mime is None:
        mime = "application/octet-stream"

    def _iter():
        with target.open("rb") as fh:
            while True:
                chunk = fh.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=mime,
        headers={"Cache-Control": "no-cache", "Content-Length": str(size)},
    )
