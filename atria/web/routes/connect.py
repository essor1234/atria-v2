"""Connect API — manage channel connections (Telegram first).

CRUD + test + enable/disable + recipient management, mirroring the MCP-server
manager (``routes/mcp.py``). Connections persist to ``~/.atria/connect.json`` via
``connect_store``; the live adapters are owned by ``connect_runtime.ConnectManager``.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atria.core.channels.connect_store import (
    Connection,
    Recipient,
    load_connect_config,
    remove_connection,
    upsert_connection,
)
from atria.core.channels.telegram import TelegramAdapter
from atria.web.connect_runtime import get_connect_manager

router = APIRouter(prefix="/api/connect", tags=["connect"])


# --------------------------------------------------------------- request models

class ConnectionCreate(BaseModel):
    type: str = "telegram"
    label: str = ""
    bot_token: str
    enabled: bool = True


class ConnectionUpdate(BaseModel):
    label: Optional[str] = None
    bot_token: Optional[str] = None
    enabled: Optional[bool] = None


class RecipientAdd(BaseModel):
    role: str = "owner"  # "owner" | "manager"
    name: str = ""
    chat_id: str


def _mask(token: str) -> str:
    if not token:
        return ""
    return token[:6] + "…" + token[-4:] if len(token) > 12 else "•••"


def _to_view(conn: Connection) -> dict:
    mgr = get_connect_manager()
    adapter = mgr.get_adapter(conn.id)
    return {
        "id": conn.id,
        "type": conn.type,
        "label": conn.label,
        "enabled": conn.enabled,
        "bot_token_masked": _mask(conn.bot_token),
        "status": adapter.status if adapter else ("enabled" if conn.enabled else "disabled"),
        "bot_username": adapter.bot_username if adapter else None,
        "last_error": adapter.last_error if adapter else None,
        "recipients": [r.model_dump() for r in conn.recipients],
        "recipient_count": len(conn.recipients),
    }


# ------------------------------------------------------------------- endpoints

@router.get("/connections")
async def list_connections() -> dict:
    cfg = load_connect_config()
    return {"connections": [_to_view(c) for c in cfg.connections]}


@router.post("/connections")
async def create_connection(body: ConnectionCreate) -> dict:
    if body.type != "telegram":
        raise HTTPException(status_code=400, detail=f"Unsupported channel type: {body.type}")
    # Validate the bot token before saving (Telegram getMe).
    me = await TelegramAdapter(body.bot_token).get_me()
    if not me.get("ok"):
        raise HTTPException(status_code=400, detail=f"Invalid bot token: {me.get('description')}")
    username = me["result"].get("username")

    conn = Connection(
        id=f"telegram-{uuid4().hex[:8]}",
        type="telegram",
        label=body.label or (username or "Telegram"),
        bot_token=body.bot_token,
        enabled=body.enabled,
    )
    upsert_connection(conn)
    if conn.enabled:
        await get_connect_manager().start_connection(conn)
    return {"success": True, "connection": _to_view(conn), "bot_username": username}


@router.put("/connections/{conn_id}")
async def update_connection(conn_id: str, body: ConnectionUpdate) -> dict:
    cfg = load_connect_config()
    conn = cfg.get(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    if body.label is not None:
        conn.label = body.label
    if body.bot_token is not None:
        conn.bot_token = body.bot_token
    if body.enabled is not None:
        conn.enabled = body.enabled
    upsert_connection(conn)

    mgr = get_connect_manager()
    await mgr.stop_connection(conn_id)
    if conn.enabled:
        await mgr.start_connection(conn)
    return {"success": True, "connection": _to_view(conn)}


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str) -> dict:
    await get_connect_manager().stop_connection(conn_id)
    if not remove_connection(conn_id):
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    return {"success": True}


@router.post("/connections/{conn_id}/test")
async def test_connection(conn_id: str) -> dict:
    conn = load_connect_config().get(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    me = await TelegramAdapter(conn.bot_token).get_me()
    if not me.get("ok"):
        return {"ok": False, "error": me.get("description")}
    return {"ok": True, "bot_username": me["result"].get("username")}


@router.post("/connections/{conn_id}/enable")
async def enable_connection(conn_id: str) -> dict:
    return await update_connection(conn_id, ConnectionUpdate(enabled=True))


@router.post("/connections/{conn_id}/disable")
async def disable_connection(conn_id: str) -> dict:
    return await update_connection(conn_id, ConnectionUpdate(enabled=False))


@router.get("/connections/{conn_id}/pending-contacts")
async def pending_contacts(conn_id: str) -> dict:
    """Chat ids that messaged the bot but aren't yet assigned a role."""
    adapter = get_connect_manager().get_adapter(conn_id)
    if adapter is None:
        return {"pending": []}
    return {"pending": [{"chat_id": cid, "name": name}
                        for cid, name in adapter.pending_contacts.items()]}


@router.post("/connections/{conn_id}/recipients")
async def add_recipient(conn_id: str, body: RecipientAdd) -> dict:
    cfg = load_connect_config()
    conn = cfg.get(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    conn.recipients = [r for r in conn.recipients if str(r.chat_id) != str(body.chat_id)]
    conn.recipients.append(Recipient(role=body.role, name=body.name, chat_id=str(body.chat_id)))
    upsert_connection(conn)
    get_connect_manager().update_allowlist(conn)  # live allowlist refresh
    return {"success": True, "connection": _to_view(conn)}


@router.delete("/connections/{conn_id}/recipients/{chat_id}")
async def remove_recipient(conn_id: str, chat_id: str) -> dict:
    cfg = load_connect_config()
    conn = cfg.get(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail=f"Connection {conn_id} not found")
    conn.recipients = [r for r in conn.recipients if str(r.chat_id) != str(chat_id)]
    upsert_connection(conn)
    get_connect_manager().update_allowlist(conn)
    return {"success": True, "connection": _to_view(conn)}
