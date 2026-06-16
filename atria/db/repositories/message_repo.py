"""CRUD for the messages table.

blocks column structure (hybrid):
  {
    "typed": [ ... ],
    "raw": { <full ChatMessage.model_dump(mode='json')> }
  }

Round-trip: load from raw when present; typed blocks are for UI rendering.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from atria.db.models import Message
from atria.db.repositories.base import BaseRepository
from atria.models.message import ChatMessage, Role, ToolCall


def _msg_to_blocks(msg: ChatMessage) -> dict:
    """Serialize ChatMessage → hybrid blocks dict."""
    typed: list[dict] = []
    if msg.thinking_trace:
        typed.append({"type": "thinking", "content": msg.thinking_trace})
    if msg.reasoning_content:
        typed.append({"type": "reasoning", "content": msg.reasoning_content})
    for tc in msg.tool_calls:
        typed.append(
            {
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "parameters": tc.parameters,
                "result": tc.result,
                "result_summary": tc.result_summary,
                "error": tc.error,
                "approved": tc.approved,
            }
        )
    if msg.content:
        typed.append({"type": "text", "content": msg.content})
    return {"typed": typed, "raw": msg.model_dump(mode="json")}


def _blocks_to_msg(blocks: dict) -> ChatMessage:
    """Deserialize hybrid blocks dict → ChatMessage (uses raw for fidelity)."""
    raw = blocks.get("raw")
    if raw:
        return ChatMessage(**raw)
    typed = blocks.get("typed", [])
    content = ""
    thinking_trace: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: list[ToolCall] = []
    for block in typed:
        btype = block.get("type")
        if btype == "text":
            content = block.get("content", "")
        elif btype == "thinking":
            thinking_trace = block.get("content")
        elif btype == "reasoning":
            reasoning_content = block.get("content")
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    parameters=block.get("parameters", {}),
                    result=block.get("result"),
                    result_summary=block.get("result_summary"),
                    error=block.get("error"),
                    approved=block.get("approved", False),
                )
            )
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "_blocks_to_msg: no raw field, reconstructing from typed blocks (lossy)"
    )
    return ChatMessage(
        role=Role.ASSISTANT if tool_calls else Role.USER,
        content=content,
        thinking_trace=thinking_trace,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
    )


class MessageRepository(BaseRepository):

    async def insert(
        self,
        conversation_id: int,
        message: ChatMessage,
        mode: str = "normal",
    ) -> int:
        blocks = _msg_to_blocks(message)
        async with self._sessionmaker() as session:
            stmt = (
                pg_insert(Message)
                .values(
                    is_deleted=False,
                    conversation_id=conversation_id,
                    role=message.role.value[:10],
                    mode=mode[:10],
                    blocks=blocks,
                )
                .returning(Message.id)
            )
            result = await session.execute(stmt)
            new_id = int(result.scalar_one())
            await session.commit()
            return new_id

    async def list_by_conversation(self, conversation_id: int) -> list[ChatMessage]:
        async with self._sessionmaker() as session:
            stmt = (
                select(Message.blocks)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.is_deleted.is_(False),
                )
                .order_by(Message.id.asc())
            )
            result = await session.execute(stmt)
        out: list[ChatMessage] = []
        for (blocks,) in result.all():
            if not isinstance(blocks, dict):
                continue
            try:
                out.append(_blocks_to_msg(blocks))
            except Exception:
                continue
        return out

    async def list_ids_by_conversation(self, conversation_id: int) -> list[int]:
        """Return live (not soft-deleted) message ids in insertion order."""
        async with self._sessionmaker() as session:
            stmt = (
                select(Message.id)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.is_deleted.is_(False),
                )
                .order_by(Message.id.asc())
            )
            result = await session.execute(stmt)
        return [int(row[0]) for row in result.all()]

    async def soft_delete_by_ids(self, ids: list[int]) -> int:
        """Soft-delete the given message ids. Returns rows affected."""
        if not ids:
            return 0
        async with self._sessionmaker() as session:
            stmt = (
                update(Message)
                .where(Message.id.in_(ids), Message.is_deleted.is_(False))
                .values(is_deleted=True)
            )
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)
