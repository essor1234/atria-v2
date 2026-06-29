"""Session management API endpoints."""

from pathlib import Path
from typing import Dict, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atria.web.state import get_state
from atria.models.api import SessionResponse as SessionInfo
from atria.web.dependencies.auth import require_authenticated_user
from atria.web.dependencies.workspace import UserWorkspace, require_workspace

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_authenticated_user)],
)


class CreateSessionRequest(BaseModel):
    """Request model for creating a new session."""

    workspace: str


@router.get("/bridge-info")
async def get_bridge_info() -> Dict[str, Any]:
    """Return bridge mode status and the TUI session ID (if active)."""
    state = get_state()
    if not state.is_bridge_mode:
        return {"bridge_mode": False, "session_id": None}
    session = await state.session_manager.get_current_session()
    return {
        "bridge_mode": True,
        "session_id": session.id if session else None,
    }


@router.post("/create")
async def create_session(
    request: CreateSessionRequest,
    user=Depends(require_authenticated_user),
    workspace: UserWorkspace = Depends(require_workspace),
) -> Dict[str, Any]:
    """Create a new session with specified workspace.

    Reuses an existing empty session for the same workspace if one exists,
    preventing users from accumulating blank sessions.

    Args:
        request: Request containing workspace path

    Returns:
        New session information

    Raises:
        HTTPException: If creation fails
    """
    try:
        state = get_state()
        owner_id = str(user.id)
        raw_workspace = (request.workspace or "").strip()
        # Default to the user's own workspace when the client sends an empty
        # value or a placeholder; otherwise honour the requested path as-is
        # (tools are shared — no sandboxing at the session boundary).
        if not raw_workspace or raw_workspace in {"default", "$WORKSPACE", "~"}:
            workspace_str = str(workspace.workspace_path)
        else:
            workspace_str = str(Path(raw_workspace).expanduser().resolve())

        # Reuse an existing empty session for this workspace if one exists
        existing_sessions = await state.list_sessions(owner_id=owner_id)
        empty_session = next(
            (
                s
                for s in existing_sessions
                if s["message_count"] == 0
                and str(Path(s["working_dir"]).expanduser().resolve()) == workspace_str
            ),
            None,
        )

        if empty_session:
            # Guard against stale index: skip if this is the currently active session
            # with in-memory messages (index may not reflect unsaved messages yet)
            current = await state.session_manager.get_current_session()
            is_stale = (
                current is not None
                and current.id == empty_session["id"]
                and len(current.messages) > 0
            )
            if not is_stale:
                success = await state.resume_session(empty_session["id"], owner_id=owner_id)
                session = await state.session_manager.get_current_session()
                if success and session:
                    return {
                        "status": "success",
                        "message": "Reusing existing empty session",
                        "session": {
                            "id": session.id,
                            "working_dir": session.working_directory or "",
                            "created_at": session.created_at.isoformat(),
                            "updated_at": session.updated_at.isoformat(),
                            "message_count": len(session.messages),
                            "total_tokens": session.total_tokens(),
                        },
                    }

        # No empty session found — create a new one
        await state.session_manager.create_session(
            working_directory=workspace_str,
            owner_id=owner_id,
            user_id=user.id,
            project_id=workspace.project_id,
        )

        session = await state.session_manager.get_current_session()

        # Force-save so the session file exists on disk for WebSocket lookups
        await state.session_manager.save_session(force=True)

        # Initialize plan file path for plan mode
        from atria.core.paths import get_paths

        plans_dir = get_paths().global_dir / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_file_path = plans_dir / f"{session.id}.md"
        state.mode_manager.set_plan_file_path(str(plan_file_path))

        return {
            "status": "success",
            "message": "Session created",
            "session": {
                "id": session.id,
                "working_dir": session.working_directory or "",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "message_count": len(session.messages),
                "total_tokens": session.total_tokens(),
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_sessions(user=Depends(require_authenticated_user)) -> List[SessionInfo]:
    """List all available sessions for the current user."""
    try:
        state = get_state()
        sessions = await state.list_sessions(owner_id=str(user.id))
        return [SessionInfo(**session) for session in sessions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current")
async def get_current_session(user=Depends(require_authenticated_user)) -> Dict[str, Any]:
    """Get the current active session for the user."""
    try:
        state = get_state()
        session = await state.session_manager.get_current_session()
        if not session or session.owner_id != str(user.id):
            raise HTTPException(status_code=404, detail="No active session")

        return {
            "id": session.id,
            "working_dir": session.working_directory or "",
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "message_count": len(session.messages),
            "total_tokens": session.total_tokens(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/resume")
async def resume_session(
    session_id: str,
    user=Depends(require_authenticated_user),
) -> Dict[str, str]:
    """Resume a specific session.

    Args:
        session_id: ID of the session to resume

    Returns:
        Status response

    Raises:
        HTTPException: If session not found or resume fails
    """
    try:
        state = get_state()

        # Check if this is the current session (newly created but not yet saved)
        current = await state.session_manager.get_current_session()
        if current and current.id == session_id:
            if current.owner_id is not None and current.owner_id != str(user.id):
                raise HTTPException(status_code=403, detail="Forbidden")
            return {"status": "success", "message": f"Session {session_id} already active"}

        # Try to load from disk with ownership enforcement
        success = await state.resume_session(session_id, owner_id=str(user.id))

        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Verify session was loaded and initialize plan file path
        current = await state.session_manager.get_current_session()
        if current:
            from atria.core.paths import get_paths

            plans_dir = get_paths().global_dir / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            plan_file_path = plans_dir / f"{current.id}.md"
            state.mode_manager.set_plan_file_path(str(plan_file_path))

        return {"status": "success", "message": f"Resumed session {session_id}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint groups split into focused submodules and mounted onto this router.
# Sub-routers carry relative paths; the prefix and auth dependency declared above
# apply to every included route. Include order preserves the original route order.
from atria.web.routes._lifecycle import router as _lifecycle_router  # noqa: E402
from atria.web.routes._filesystem import router as _filesystem_router  # noqa: E402
from atria.web.routes._model import router as _model_router  # noqa: E402

router.include_router(_lifecycle_router)
router.include_router(_filesystem_router)
router.include_router(_model_router)
