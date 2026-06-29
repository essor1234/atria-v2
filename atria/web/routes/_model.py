"""Per-session model overlay endpoints (get/update/delete)."""

from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from atria.web.state import get_state
from atria.web.dependencies.auth import require_authenticated_user

router = APIRouter()


# ========================================================================
# Session Model Overlay Endpoints
# ========================================================================


class SessionModelUpdate(BaseModel):
    """Request body for updating session model overlay."""

    model: str | None = None
    model_thinking: str | None = None
    model_vlm: str | None = None
    model_critique: str | None = None
    model_compact: str | None = None


@router.get("/{session_id}/model")
async def get_session_model_overlay(
    session_id: str,
    user=Depends(require_authenticated_user),
) -> Dict[str, Any]:
    try:
        state = get_state()
        session = await state.session_manager.get_session_by_id(session_id, owner_id=str(user.id))

        overlay = session.metadata.get("session_model") or {}
        return overlay

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{session_id}/model")
async def update_session_model(
    session_id: str,
    body: SessionModelUpdate,
    user=Depends(require_authenticated_user),
) -> Dict[str, str]:
    """Set or update the session-model overlay."""
    try:
        from atria.core.runtime.session_model import (
            SESSION_MODEL_FIELDS,
            SessionModelManager,
            set_session_model,
        )

        state = get_state()

        # Build overlay from non-None fields
        overlay: Dict[str, str] = {}
        for field_name in SESSION_MODEL_FIELDS:
            value = getattr(body, field_name, None)
            if value is not None:
                overlay[field_name] = value

        if not overlay:
            raise HTTPException(status_code=400, detail="No model fields provided")

        # Load the session
        current = await state.session_manager.get_current_session()
        is_current = current and current.id == session_id

        if is_current:
            session = current
        else:
            try:
                session = await state.session_manager.get_session_by_id(
                    session_id, owner_id=str(user.id)
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Apply overlay to live config if this is the active session
        if is_current:
            config = state.config_manager.get_config()
            # Restore previous overlay if any
            if hasattr(state, "_session_model_manager") and state._session_model_manager:
                state._session_model_manager.restore()
            mgr = SessionModelManager(config)
            mgr.apply(overlay)
            state._session_model_manager = mgr

        # Persist to session metadata
        set_session_model(session, overlay)
        await state.session_manager.save_session(session)

        return {"status": "success", "message": "Session model updated"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}/model")
async def delete_session_model(
    session_id: str, user=Depends(require_authenticated_user)
) -> Dict[str, str]:
    try:
        from atria.core.runtime.session_model import clear_session_model

        state = get_state()

        current = await state.session_manager.get_current_session()
        is_current = current and current.id == session_id

        if is_current:
            session = current
            # Restore live config
            if hasattr(state, "_session_model_manager") and state._session_model_manager:
                state._session_model_manager.restore()
                state._session_model_manager = None
        else:
            try:
                session = await state.session_manager.get_session_by_id(
                    session_id, owner_id=str(user.id)
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        clear_session_model(session)
        await state.session_manager.save_session(session)

        return {"status": "success", "message": "Session model cleared"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
