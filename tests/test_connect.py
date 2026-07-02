"""Tests for the "Connect" subsystem: connection store, MessageRouter dispatch,
and the Telegram adapter's allowlist/routing logic.

Async paths are driven via ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio

from atria.core.channels.base import InboundMessage
from atria.core.channels.connect_store import (
    Connection,
    ConnectConfig,
    Recipient,
    load_connect_config,
    remove_connection,
    save_connect_config,
    upsert_connection,
)
from atria.core.channels.mock import MockChannelAdapter
from atria.core.channels.router import MessageRouter
from atria.core.channels.telegram import TelegramAdapter
from atria.models.session import Session


# --------------------------------------------------------------- connect_store

def test_connect_store_roundtrip(tmp_path):
    p = tmp_path / "connect.json"
    cfg = ConnectConfig(connections=[
        Connection(id="t1", type="telegram", label="Acme", bot_token="123:ABC",
                   recipients=[Recipient(role="owner", name="me", chat_id="111")])
    ])
    save_connect_config(cfg, p)

    loaded = load_connect_config(p)
    conn = loaded.get("t1")
    assert conn is not None
    assert conn.label == "Acme"
    assert conn.bot_token == "123:ABC"
    assert conn.allowed_chat_ids() == {"111"}

    upsert_connection(Connection(id="t1", label="Acme2", bot_token="123:ABC"), p)
    assert load_connect_config(p).get("t1").label == "Acme2"

    assert remove_connection("t1", p) is True
    assert load_connect_config(p).get("t1") is None
    assert remove_connection("t1", p) is False


def test_connect_store_missing_file(tmp_path):
    # Loading a non-existent file yields an empty config, not a crash.
    cfg = load_connect_config(tmp_path / "nope.json")
    assert cfg.connections == []


# ------------------------------------------------------------- fake session mgr

class _FakeSessionManager:
    """In-memory SessionManager with channel-user reuse, enough for the router."""

    def __init__(self):
        self._by_key = {}
        self._by_id = {}
        self._n = 0

    async def find_session_by_channel_user(self, channel, user_id, thread_id=None):
        s = self._by_key.get((channel, user_id, thread_id))
        return s.get_metadata() if s else None

    async def load_session(self, session_id, owner_id=None):
        return self._by_id[session_id]

    async def create_session(self, working_directory=None, channel="cli", channel_user_id="",
                             chat_type="direct", thread_id=None, delivery_context=None,
                             workspace_confirmed=True, **kw):
        self._n += 1
        s = Session(id=str(self._n), working_directory=working_directory, channel=channel,
                    channel_user_id=channel_user_id, chat_type=chat_type, thread_id=thread_id,
                    delivery_context=delivery_context or {}, workspace_confirmed=workspace_confirmed)
        self._by_key[(channel, channel_user_id, thread_id)] = s
        self._by_id[s.id] = s
        return s

    async def save_session(self, session=None, **kw):
        return None


# ------------------------------------------------------------------ router loop

def test_router_dispatch_and_session_reuse():
    async def _run():
        sm = _FakeSessionManager()

        async def agent(session, text):
            turns = len([m for m in session.messages if m.role.value == "user"])
            return f"echo:{text} (turns={turns})"

        router = MessageRouter(sm, agent_executor=agent, default_workspace="/tmp/ws")
        mock = MockChannelAdapter("telegram:test")
        await mock.start()
        router.register_adapter(mock)

        await router.handle_inbound(InboundMessage(
            channel="telegram:test", user_id="111", text="hi", metadata={"chat_id": "111"}))
        out = mock.get_last_outbound()
        assert out is not None and out.text.startswith("echo:hi")
        # delivery_context carries chat_id so the reply can be routed back
        assert mock.delivery_contexts[-1].get("chat_id") == "111"
        # workspace prompt was skipped (default_workspace) — only the echo went out
        assert len(mock.outbound_messages) == 1

        # second message from the same chat reuses the session (turn count grows)
        await router.handle_inbound(InboundMessage(
            channel="telegram:test", user_id="111", text="again", metadata={"chat_id": "111"}))
        assert "turns=2" in mock.get_last_outbound().text

    asyncio.run(_run())


# --------------------------------------------------------------- telegram logic

def test_telegram_allowlist_and_routing():
    async def _run():
        routed = []

        class _FakeRouter:
            async def handle_inbound(self, msg):
                routed.append(msg)

        ad = TelegramAdapter("tok", channel_name="telegram:t", router=_FakeRouter(),
                             allowed_chat_ids={"111"})
        ad._client = "dummy"  # prevent real httpx client creation in send()
        sent = []

        async def fake_api(method, **params):
            sent.append((method, params))
            return {"ok": True, "result": {}}

        ad._api = fake_api

        # authorized text → routed to the agent, nothing sent
        await ad._handle_update({"update_id": 1, "message": {
            "message_id": 5, "chat": {"id": 111, "type": "private", "username": "boss"},
            "text": "hello"}})
        assert routed and routed[0].text == "hello"
        assert routed[0].metadata["chat_id"] == "111"
        assert not sent

        # unauthorized → recorded as pending + a "not authorized" reply
        await ad._handle_update({"update_id": 2, "message": {
            "message_id": 6, "chat": {"id": 999, "type": "private", "first_name": "X"},
            "text": "hi"}})
        assert "999" in ad.pending_contacts
        assert any(m == "sendMessage" for m, _ in sent)
        assert len(routed) == 1  # not routed to the agent

        # /start from an authorized user → greeting, not an agent turn
        routed.clear()
        sent.clear()
        await ad._handle_update({"update_id": 3, "message": {
            "message_id": 7, "chat": {"id": 111, "type": "private", "username": "boss"},
            "text": "/start"}})
        assert not routed
        assert any(m == "sendMessage" for m, _ in sent)

        # adding 999 to the allowlist clears it from pending
        ad.update_allowlist({"111", "999"})
        assert "999" not in ad.pending_contacts

    asyncio.run(_run())
