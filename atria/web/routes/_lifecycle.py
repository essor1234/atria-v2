"""Session lifecycle endpoints: messages, deletion, turn deletion, export."""

from typing import Dict, List, Any

from fastapi import APIRouter, Depends, HTTPException

from atria.web.state import get_state
from atria.models.api import MessageResponse, tool_call_to_response as tool_call_to_info
from atria.web.dependencies.auth import require_authenticated_user

router = APIRouter()


@router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    user=Depends(require_authenticated_user),
) -> List[MessageResponse]:
    """Get messages for a specific session without changing the current session.

    Uses get_session_by_id() which is non-mutating — it does not change
    the session_manager's current_session pointer.

    Args:
        session_id: ID of the session to read messages from

    Returns:
        List of messages

    Raises:
        HTTPException: If session not found
    """
    try:
        state = get_state()

        # Try non-mutating read first
        try:
            session = await state.session_manager.get_session_by_id(
                session_id, owner_id=str(user.id)
            )
        except FileNotFoundError:
            # Session might be newly created but not saved to disk yet
            current = await state.session_manager.get_current_session()
            if current and current.id == session_id:
                session = current
            else:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        visible_messages = [m for m in session.messages if not m.metadata.get("display_hidden")]
        return [
            MessageResponse(
                role=msg.role.value,
                content=msg.content,
                timestamp=(
                    msg.timestamp.isoformat()
                    if hasattr(msg, "timestamp") and msg.timestamp
                    else None
                ),
                tool_calls=(
                    [tool_call_to_info(tc) for tc in msg.tool_calls] if msg.tool_calls else None
                ),
                thinking_trace=msg.thinking_trace,
                reasoning_content=msg.reasoning_content,
                metadata=msg.metadata if msg.metadata else None,
            )
            for msg in visible_messages
        ]

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str, user=Depends(require_authenticated_user)
) -> Dict[str, str]:
    """Delete a specific session.

    Args:
        session_id: ID of the session to delete

    Returns:
        Status response

    Raises:
        HTTPException: If deletion fails
    """
    try:
        state = get_state()

        state = get_state()
        try:
            await state.session_manager.get_session_by_id(session_id, owner_id=str(user.id))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        await state.session_manager.delete_session(session_id)

        current_session = await state.session_manager.get_current_session()
        if current_session and current_session.id == session_id:
            state.session_manager.current_session = None

        return {"status": "success", "message": f"Session {session_id} deleted"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}/turns/{turn_index}")
async def delete_session_turn(
    session_id: str,
    turn_index: int,
    user=Depends(require_authenticated_user),
) -> Dict[str, Any]:
    """Soft-delete a turn slice from a session and broadcast the replacement.

    A "turn" begins at a user message and extends through subsequent
    non-user messages. ``turn_index`` must point at a USER message.
    """
    state = get_state()

    # Ownership check (consistent with other routes that read this session).
    try:
        session = await state.session_manager.get_session_by_id(session_id, owner_id=str(user.id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    before_count = len(session.messages)

    try:
        remaining = await state.session_manager.delete_turn(session_id, turn_index)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except IndexError:
        raise HTTPException(status_code=404, detail="turn_index out of range")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    visible = [m for m in remaining if not m.metadata.get("display_hidden")]
    payload = [
        MessageResponse(
            role=m.role.value,
            content=m.content,
            timestamp=(
                m.timestamp.isoformat() if hasattr(m, "timestamp") and m.timestamp else None
            ),
            tool_calls=([tool_call_to_info(tc) for tc in m.tool_calls] if m.tool_calls else None),
            thinking_trace=m.thinking_trace,
            reasoning_content=m.reasoning_content,
            metadata=m.metadata if m.metadata else None,
        )
        for m in visible
    ]
    payload_dicts = [p.model_dump() for p in payload]

    # Best-effort broadcast so other connected tabs reconcile.
    try:
        from atria.web.state import broadcast_to_all_clients

        await broadcast_to_all_clients(
            {
                "type": "session_messages_replaced",
                "session_id": session_id,
                "messages": payload_dicts,
            }
        )
    except Exception:
        pass

    deleted_count = before_count - len(remaining)
    return {"deleted": deleted_count, "messages": payload_dicts}


@router.get("/{session_id}/export")
async def export_session(
    session_id: str, user=Depends(require_authenticated_user)
) -> Dict[str, Any]:
    """Export a session as JSON.

    Args:
        session_id: ID of the session to export

    Returns:
        Session data

    Raises:
        HTTPException: If export fails
    """
    try:
        state = get_state()

        try:
            session = await state.session_manager.get_session_by_id(
                session_id, owner_id=str(user.id)
            )
        except FileNotFoundError:
            # Might be the current session not yet saved to disk
            current = await state.session_manager.get_current_session()
            if current and current.id == session_id:
                session = current
            else:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return {
            "id": session.id,
            "working_dir": session.working_directory or "",
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "messages": [
                {
                    "role": msg.role.value,
                    "content": msg.content,
                    "timestamp": (
                        msg.timestamp.isoformat()
                        if hasattr(msg, "timestamp") and msg.timestamp
                        else None
                    ),
                }
                for msg in session.messages
            ],
            "token_usage": session.token_usage,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
