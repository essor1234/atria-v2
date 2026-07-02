"""push_block persistence must be mandatory and surface failures."""
from __future__ import annotations

import pytest
from atria.web import ui_bridge


class _FakeSessionMgr:
    def __init__(self, fail: bool = False):
        self.saved = []
        self._fail = fail

    async def get_session_by_id(self, sid, owner_id=None):
        return _FakeSession(self)

    async def save_session(self, sess):
        if self._fail:
            raise RuntimeError("db down")
        self.saved.append(sess)


class _FakeSession:
    def __init__(self, mgr):
        self._mgr = mgr
        self.messages = []

    def add_message(self, msg):
        self.messages.append(msg)


def test_persist_failure_raises():
    mgr = _FakeSessionMgr(fail=True)
    with pytest.raises(ui_bridge.BlockPersistError):
        ui_bridge._persist_block_message_sync(
            session_id="s1",
            metadata={"block_id": "b1", "module": "m", "block": "x"},
            session_manager=mgr,
        )


def test_persist_success_writes_custom_block_message():
    mgr = _FakeSessionMgr(fail=False)
    ui_bridge._persist_block_message_sync(
        session_id="s1",
        metadata={"block_id": "b1", "module": "m", "block": "x"},
        session_manager=mgr,
    )
    assert len(mgr.saved) == 1
    msg = mgr.saved[0].messages[-1]
    assert msg.role.value == "custom_block"
    assert msg.metadata["block_id"] == "b1"
