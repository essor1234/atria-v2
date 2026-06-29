"""Pure digest rendering: dedup + simple priority + token-budget truncation."""
from __future__ import annotations

from atria.core.blackboard.models import Note

_PRIORITY = {"PATCH_SUMMARY": 0, "CLAIM": 1, "FAIL": 2, "FACT": 3, "OBSERVED": 4, "TRIED": 5}
_CHARS_PER_TOKEN = 4
_FORMAT_OVERHEAD_CHARS = 25


def render_digest(notes: list[Note], viewer_id: int, window_tokens: int) -> str:
    """Render a deduped, priority-ordered, budget-truncated digest.

    Args:
        notes: All notes currently on the blackboard.
        viewer_id: The reading thread's id (reserved for 2b peer framing; unused in 2a
            beyond inclusion).
        window_tokens: Token budget; entries beyond it are dropped (priority, then newest).

    Returns:
        Newline-joined "[t{thread}/{TYPE}] {content}" lines, or "" when nothing fits.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Note] = []
    for n in notes:
        key = (n.type, n.content)
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    # priority asc, then newest (ts desc)
    unique.sort(key=lambda n: (_PRIORITY.get(n.type, 9), -n.ts))

    budget = window_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    used = 0
    for n in unique:
        line = f"[t{n.thread_id}/{n.type}] {n.content}"
        cost = len(line) + _FORMAT_OVERHEAD_CHARS
        if used + cost > budget:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)
