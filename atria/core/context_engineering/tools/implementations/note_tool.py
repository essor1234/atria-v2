"""The NOTE tool: write verified typed notes to the run's shared blackboard."""
from __future__ import annotations

from typing import Any

_NONE = "(none)"


def parse_note_body(text: str) -> list[dict]:
    """Parse up to a few `<TYPE> <content>` lines into note dicts. `(none)` lines are skipped."""
    notes: list[dict] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.lower() == _NONE:
            continue
        parts = s.split(None, 1)
        if len(parts) != 2:
            continue
        notes.append({"type": parts[0].strip(), "content": parts[1].strip()})
    return notes


def execute_note(arguments: dict[str, Any], blackboard: Any = None) -> dict[str, Any]:
    """Write the parsed notes to the blackboard handle; soft no-op if none attached."""
    parsed = parse_note_body(arguments.get("body", ""))
    if blackboard is None:
        return {"success": True, "output": "no blackboard attached; note skipped"}
    if not parsed:
        return {"success": True, "output": "ok:0/0"}
    status = blackboard.write(parsed)
    return {"success": True, "output": status}
