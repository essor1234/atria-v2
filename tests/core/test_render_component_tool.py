from __future__ import annotations

import pytest
from atria.core.context_engineering.tools.implementations.render_component_tool import (
    RenderComponentHandler,
)
from atria.web import ui_bridge


class _Ctx:
    def __init__(self, sid):
        self.ui_callback = type("CB", (), {"session_id": sid})()


def test_render_missing_module_errors():
    h = RenderComponentHandler()
    res = h.render({"block": "form"}, _Ctx("s1"))
    assert res["success"] is False
    assert "module" in res["error"].lower()


def test_render_pushes_block(monkeypatch):
    calls = {}

    def fake_push_block(module, block, props=None, *, height="auto", title=None,
                        session_id=None, persist=True, **kw):
        calls.update(module=module, block=block, props=props, session_id=session_id,
                     persist=persist)
        return "blk-123"

    monkeypatch.setattr(ui_bridge, "push_block", fake_push_block)
    h = RenderComponentHandler()
    res = h.render(
        {"module": "warehouse", "block": "item_form", "props": {"x": 1}, "title": "Form"},
        _Ctx("s1"),
    )
    assert res["success"] is True
    assert res["block_id"] == "blk-123"
    assert calls["module"] == "warehouse"
    assert calls["persist"] is True
    assert calls["session_id"] == "s1"


def test_render_block_not_found(monkeypatch):
    def fake_push_block(*a, **k):
        raise ui_bridge.BlockNotFound("warehouse/blocks/nope.html not found")

    monkeypatch.setattr(ui_bridge, "push_block", fake_push_block)
    h = RenderComponentHandler()
    res = h.render({"module": "warehouse", "block": "nope"}, _Ctx("s1"))
    assert res["success"] is False
    assert "not found" in res["error"].lower()
