"""Tests for the NOTE tool: parse_note_body and execute_note."""
from atria.core.context_engineering.tools.implementations.note_tool import (
    execute_note,
    parse_note_body,
)


def test_parse_multiline_body():
    body = "FACT a.py:1 does x\nTRIED added guard\n(none)"
    parsed = parse_note_body(body)
    assert {"type": "FACT", "content": "a.py:1 does x"} in parsed
    assert {"type": "TRIED", "content": "added guard"} in parsed
    assert all(p["content"] != "(none)" for p in parsed)


def test_parse_none_only_is_empty():
    assert parse_note_body("(none)") == []


def test_execute_note_writes_via_handle():
    class _Handle:
        def __init__(self):
            self.calls = []

        def write(self, notes):
            self.calls.append(notes)
            return "ok:1/1"

    h = _Handle()
    out = execute_note({"body": "FACT found it"}, blackboard=h)
    assert out["success"] is True
    assert out["output"] == "ok:1/1"
    assert h.calls == [[{"type": "FACT", "content": "found it"}]]


def test_execute_note_without_blackboard_is_soft_noop():
    out = execute_note({"body": "FACT x"}, blackboard=None)
    assert out["success"] is True
    assert "no blackboard" in out["output"].lower()
