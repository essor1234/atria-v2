"""Render the Shared Lessons context section from a blackboard handle."""

from __future__ import annotations

from typing import Any

_HEADER = "## Shared Lessons (verified notes from this task's solvers)\n"


def render_shared_lessons_section(blackboard: Any) -> str:
    """Return a titled digest section, or "" when there is nothing to show.

    Args:
        blackboard: A BlackboardHandle with a ``render()`` method, or None.

    Returns:
        A titled section string when the blackboard has non-empty content,
        otherwise an empty string.  Never raises — missing or empty blackboard
        degrades silently so prompt composition is never broken.
    """
    if blackboard is None:
        return ""
    digest = blackboard.render()
    if not digest:
        return ""
    return _HEADER + digest
