"""Real-DB tests for MessageRepository on SQLAlchemy ORM."""

from __future__ import annotations

import os
import pytest

from atria.db.connection import get_sessionmaker, init_schema, close_engine
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.message_repo import MessageRepository
from atria.db.repositories.user_repo import UserRepository
from atria.models.message import ChatMessage, Role


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for real-Postgres ORM tests",
)


@pytest.fixture
async def sm():
    await init_schema()
    sm = await get_sessionmaker()
    yield sm
    await close_engine()


async def test_insert_and_list_roundtrip_preserves_content(sm):
    users = UserRepository(sm)
    convs = ConversationRepository(sm)
    msgs = MessageRepository(sm)
    uid = await users.upsert_by_email("orm-msg-1@atria.local")
    cid = await convs.create(None, uid, "msg", "normal")
    original = ChatMessage(role=Role.USER, content="hello world")
    await msgs.insert(cid, original)
    loaded = await msgs.list_by_conversation(cid)
    assert len(loaded) == 1
    assert loaded[0].role == Role.USER
    assert loaded[0].content == "hello world"


async def test_list_orders_by_id_ascending(sm):
    users = UserRepository(sm)
    convs = ConversationRepository(sm)
    msgs = MessageRepository(sm)
    uid = await users.upsert_by_email("orm-msg-2@atria.local")
    cid = await convs.create(None, uid, "order", "normal")
    await msgs.insert(cid, ChatMessage(role=Role.USER, content="first"))
    await msgs.insert(cid, ChatMessage(role=Role.ASSISTANT, content="second"))
    loaded = await msgs.list_by_conversation(cid)
    assert [m.content for m in loaded] == ["first", "second"]


async def test_custom_block_role_roundtrip_preserved(sm):
    users = UserRepository(sm)
    convs = ConversationRepository(sm)
    msgs = MessageRepository(sm)
    uid = await users.upsert_by_email("orm-msg-cb@atria.local")
    cid = await convs.create(None, uid, "cb", "normal")
    original = ChatMessage(
        role=Role.CUSTOM_BLOCK,
        content="",
        metadata={"block_id": "abc123", "module": "warehouse", "block": "item_form"},
    )
    await msgs.insert(cid, original)
    loaded = await msgs.list_by_conversation(cid)
    assert len(loaded) == 1
    assert loaded[0].role == Role.CUSTOM_BLOCK
    assert loaded[0].metadata["block_id"] == "abc123"
    assert loaded[0].metadata["module"] == "warehouse"
    from sqlalchemy import text

    async with sm() as s:
        row = (
            await s.execute(text("SELECT role FROM messages WHERE conversation_id=:c"), {"c": cid})
        ).first()
    assert row[0] == "custom_block"  # previously truncated to "custom_blo"
