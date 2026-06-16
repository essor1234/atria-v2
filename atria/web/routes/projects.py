"""Project and conversation management endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atria.core.workspace.manager import (
    project_path,
    conversation_path,
    ensure_path,
    slugify,
)
from atria.db.connection import get_sessionmaker
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.project_repo import ProjectRepository
from atria.web.dependencies.auth import require_authenticated_user
from atria.web.state import get_state

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(require_authenticated_user)],
)


class CreateProjectRequest(BaseModel):
    name: str


class CreateConversationRequest(BaseModel):
    name: str


def _user_slug(user: Any) -> str:
    name = (user.username or "").strip() or user.email.split("@")[0]
    return slugify(name)


@router.get("")
async def list_projects(user=Depends(require_authenticated_user)) -> list[dict]:
    sm = await get_sessionmaker()
    repo = ProjectRepository(sm)
    rows = await repo.list_by_user(user.id)
    return [
        {
            "id": str(row["id"]),
            "name": row["title"],
            "workspace_path": row["workspace_path"] or "",
            "created_at": row["created_at"].isoformat(),
            "conversation_count": row["conversation_count"],
        }
        for row in rows
    ]


@router.post("")
async def create_project(
    request: CreateProjectRequest,
    user=Depends(require_authenticated_user),
) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name cannot be empty")

    path = project_path(_user_slug(user), name)
    ensure_path(path)

    sm = await get_sessionmaker()
    repo = ProjectRepository(sm)
    project_id = await repo.create(
        user_id=user.id,
        title=name,
        workspace_path=str(path),
    )
    return {
        "id": str(project_id),
        "name": name,
        "workspace_path": str(path),
        "created_at": None,
        "conversation_count": 0,
    }


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    user=Depends(require_authenticated_user),
) -> dict:
    sm = await get_sessionmaker()
    repo = ProjectRepository(sm)
    deleted = await repo.soft_delete(project_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True}


@router.get("/{project_id}/conversations")
async def list_conversations(
    project_id: int,
    user=Depends(require_authenticated_user),
) -> list[dict]:
    sm = await get_sessionmaker()
    proj_repo = ProjectRepository(sm)
    project = await proj_repo.get_by_id_and_user(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    conv_repo = ConversationRepository(sm)
    rows = await conv_repo.list_by_project(project_id)
    return [
        {
            "id": str(row["id"]),
            "name": row["title"] or f"Conversation {row['id']}",
            "project_id": str(project_id),
            "working_directory": row["working_directory"] or "",
            "message_count": row["message_count"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": (row["updated_at"] or row["created_at"]).isoformat(),
        }
        for row in rows
    ]


@router.post("/{project_id}/conversations")
async def create_conversation(
    project_id: int,
    request: CreateConversationRequest,
    user=Depends(require_authenticated_user),
) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Conversation name cannot be empty")

    sm = await get_sessionmaker()
    proj_repo = ProjectRepository(sm)
    project = await proj_repo.get_by_id_and_user(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    workspace = project["workspace_path"]
    if not workspace:
        raise HTTPException(status_code=400, detail="Project has no workspace path")

    conv_dir = conversation_path(Path(workspace), name)
    ensure_path(conv_dir)

    state = get_state()
    session = await state.session_manager.create_session(
        working_directory=str(conv_dir),
        channel="web",
        owner_id=str(user.id),
        project_id=project_id,
        user_id=user.id,
    )
    await state.session_manager.set_title(session.id, name)
    await state.session_manager.save_session(force=True)

    return {
        "id": session.id,
        "name": name,
        "project_id": str(project_id),
        "working_directory": str(conv_dir),
        "message_count": 0,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


@router.delete("/{project_id}/conversations/{conversation_id}")
async def delete_conversation(
    project_id: int,
    conversation_id: str,
    user=Depends(require_authenticated_user),
) -> dict:
    sm = await get_sessionmaker()
    proj_repo = ProjectRepository(sm)
    project = await proj_repo.get_by_id_and_user(project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    state = get_state()
    await state.session_manager.delete_session(conversation_id)
    return {"ok": True}
