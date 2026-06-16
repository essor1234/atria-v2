"""Tests for chat-message action endpoints (copy/delete)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.context_engineering.history.session_manager.pg_manager import PgSessionManager
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.message_repo import MessageRepository
from atria.models.message import ChatMessage, Role


@pytest.mark.asyncio
async def test_list_ids_by_conversation_returns_in_insertion_order(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    conv_id = await conv_repo.create(
        project_id=None,
        user_id=None,
        title=None,
        mode="normal",
        working_directory=None,
    )

    inserted: list[int] = []
    for content in ["hello", "world", "again"]:
        inserted.append(
            await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content=content))
        )

    ids = await msg_repo.list_ids_by_conversation(conv_id)
    assert ids == inserted


@pytest.mark.asyncio
async def test_soft_delete_by_ids_marks_rows_deleted(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    conv_id = await conv_repo.create(
        project_id=None,
        user_id=None,
        title=None,
        mode="normal",
        working_directory=None,
    )
    ids = [
        await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content="a")),
        await msg_repo.insert(conv_id, ChatMessage(role=Role.ASSISTANT, content="b")),
        await msg_repo.insert(conv_id, ChatMessage(role=Role.USER, content="c")),
    ]

    deleted = await msg_repo.soft_delete_by_ids([ids[0], ids[1]])
    assert deleted == 2

    remaining = await msg_repo.list_by_conversation(conv_id)
    assert [m.content for m in remaining] == ["c"]


@pytest_asyncio.fixture
async def pg_manager_with_session(db_session, temp_project):
    """PgSessionManager with an active session backed by temp_project."""
    mgr = PgSessionManager(sessionmaker=db_session)
    session = await mgr.create_session(
        working_directory=temp_project["workspace_path"],
        project_id=temp_project["id"],
        user_id=temp_project["user_id"],
    )
    return mgr, session


@pytest.mark.asyncio
async def test_delete_turn_drops_user_message_only(pg_manager_with_session):
    mgr, session = pg_manager_with_session

    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.USER, content="u2"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a2"), auto_save_interval=1)

    # Delete the second user turn (turn_index = 2): drops u2 + a2.
    remaining = await mgr.delete_turn(session.id, turn_index=2)
    assert [m.content for m in remaining] == ["u1", "a1"]


@pytest.mark.asyncio
async def test_delete_turn_rejects_out_of_range(pg_manager_with_session):
    mgr, session = pg_manager_with_session
    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)

    with pytest.raises(IndexError):
        await mgr.delete_turn(session.id, turn_index=5)


@pytest.mark.asyncio
async def test_delete_turn_rejects_when_not_user_message(pg_manager_with_session):
    mgr, session = pg_manager_with_session
    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a1"), auto_save_interval=1)

    with pytest.raises(ValueError):
        await mgr.delete_turn(session.id, turn_index=1)  # assistant, not user


# ── Route tests ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_route_client(db_session, temp_project, monkeypatch):
    """A TestClient wired to a PgSessionManager with two seeded user turns.

    Yields ``(client, session_id, second_user_turn_index)``.
    """
    from atria.web.routes.sessions import router as sessions_router
    from atria.web.dependencies.auth import require_authenticated_user
    from atria.web import state as state_module

    mgr = PgSessionManager(sessionmaker=db_session)
    session = await mgr.create_session(
        working_directory=temp_project["workspace_path"],
        project_id=temp_project["id"],
        user_id=temp_project["user_id"],
    )

    # Seed two user turns: [u1, a1, u2, a2]
    await mgr.add_message(ChatMessage(role=Role.USER, content="u1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a1"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.USER, content="u2"), auto_save_interval=1)
    await mgr.add_message(ChatMessage(role=Role.ASSISTANT, content="a2"), auto_save_interval=1)

    # Stub WebState exposing only the surface the route touches.
    stub_state = SimpleNamespace(
        session_manager=mgr,
        get_ws_clients=lambda: [],
    )
    monkeypatch.setattr(state_module, "_state", stub_state)

    app = FastAPI()
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
        id=temp_project["user_id"]
    )
    app.include_router(sessions_router)

    with TestClient(app) as client:
        yield client, session.id, 2  # turn_index=2 = the second user message


def test_delete_turn_endpoint_success(seeded_route_client):
    client, sid, turn_index = seeded_route_client
    r = client.delete(f"/api/sessions/{sid}/turns/{turn_index}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 2
    assert isinstance(body["messages"], list)
    contents = [m["content"] for m in body["messages"]]
    assert contents == ["u1", "a1"]


def test_delete_turn_endpoint_out_of_range_returns_404(seeded_route_client):
    client, sid, _ = seeded_route_client
    r = client.delete(f"/api/sessions/{sid}/turns/9999")
    assert r.status_code == 404


def test_delete_turn_endpoint_rejects_non_user_index_404(seeded_route_client):
    client, sid, _ = seeded_route_client
    # index 1 is the assistant message after u1
    r = client.delete(f"/api/sessions/{sid}/turns/1")
    assert r.status_code == 404
