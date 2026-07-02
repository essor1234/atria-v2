from __future__ import annotations

import pytest
from atria.web.websocket import WebSocketManager


class _FakeWS:
    pass


@pytest.fixture
def mgr(monkeypatch):
    m = WebSocketManager()
    m.sent = []

    async def _b(msg):
        m.sent.append(msg)

    m.broadcast = _b  # type: ignore
    return m


async def test_subscribe_records_interest(mgr, monkeypatch):
    from atria.web import state as _state

    class _Cfg:
        class web:
            class iframe_rpc:
                tool_allowlist = ["events.subscribe"]
                config_read_keys = []

    class _CfgMgr:
        def get_config(self):
            return _Cfg()

    class _State:
        config_manager = _CfgMgr()

        async def get_current_session_id(self):
            return "s1"

    import atria.web.websocket as _ws

    monkeypatch.setattr(_state, "get_state", lambda: _State())
    monkeypatch.setattr(_ws, "get_state", lambda: _State())
    await mgr._handle_block_rpc(
        _FakeWS(),
        {
            "data": {
                "block_id": "b1",
                "req_id": "r1",
                "method": "events.subscribe",
                "args": {"events": ["tool_call"]},
                "session_id": "s1",
            }
        },
    )
    assert "b1" in mgr._block_feed_subs.get("s1", set())


def test_forward_to_feed_emits_block_event_feed(mgr):
    mgr._block_feed_subs = {"s1": {"b1"}}
    mgr.forward_to_block_feed("s1", "tool_call", {"tool_name": "read_file"})
    feed = [m for m in mgr.sent if m.get("type") == "block_event_feed"]
    assert feed and feed[0]["data"]["block_id"] == "b1"
    assert feed[0]["data"]["event"] == "tool_call"
