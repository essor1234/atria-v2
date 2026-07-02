from __future__ import annotations

from atria.models.config import IframeRpcConfig


def test_default_allowlist_includes_read_gates():
    cfg = IframeRpcConfig()
    for m in ("chat.get_messages", "chat.get_session", "artifact.list", "config.read"):
        assert m in cfg.tool_allowlist


def test_write_gates_not_default():
    cfg = IframeRpcConfig()
    for m in ("tool.invoke", "session.send_user_message", "module.rpc"):
        assert m not in cfg.tool_allowlist


def test_config_read_keys_whitelist_is_safe():
    cfg = IframeRpcConfig()
    # Whitelist must not expose secret-bearing sections.
    joined = " ".join(cfg.config_read_keys).lower()
    assert "api_key" not in joined
    assert "secret" not in joined


import pytest
from atria.web.websocket import WebSocketManager


class _FakeWS:
    def __init__(self):
        self.sent = []


@pytest.fixture
def mgr(monkeypatch):
    m = WebSocketManager()
    m.broadcast = _record(m)  # type: ignore
    return m


def _record(m):
    async def _b(msg):
        m.last = msg
    return _b


async def test_config_read_returns_whitelisted_only(mgr, monkeypatch):
    from atria.web import state as _state

    class _Cfg:
        class web:
            iframe_rpc = IframeRpcConfig()
        model = "gpt-4"
        simple_mode = True

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
        {"data": {"block_id": "b1", "req_id": "r1", "method": "config.read",
                  "args": {"keys": ["model", "api_key"]}, "session_id": "s1"}},
    )
    assert mgr.last["data"]["ok"] is True
    data = mgr.last["data"]["data"]
    assert data.get("model") == "gpt-4"
    assert "api_key" not in data
