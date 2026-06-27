"""Tests for render_shared_lessons_section (Task 8 — context injection)."""

from atria.core.blackboard.injection import render_shared_lessons_section


def test_section_empty_when_no_blackboard():
    assert render_shared_lessons_section(None) == ""


def test_section_empty_when_digest_blank():
    class _H:
        def render(self) -> str:
            return ""

    assert render_shared_lessons_section(_H()) == ""


def test_section_wraps_digest():
    class _H:
        def render(self) -> str:
            return "[t0/FACT] a"

    out = render_shared_lessons_section(_H())
    assert "Shared Lessons" in out
    assert "[t0/FACT] a" in out
