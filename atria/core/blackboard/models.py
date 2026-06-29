"""Typed-note model and size caps for the shared blackboard."""
from __future__ import annotations

from dataclasses import dataclass

VALID_TYPES: tuple[str, ...] = ("FACT", "TRIED", "OBSERVED", "FAIL", "CLAIM", "PATCH_SUMMARY")
MAX_CONTENT_CHARS = 100
# PATCH_SUMMARY uses the structured "files=A | idea=B | evidence=C | risk=D" schema,
# which doesn't fit the 100-char durable-note cap.
MAX_PATCH_SUMMARY_CHARS = 300


@dataclass(frozen=True)
class Note:
    """One typed entry on the blackboard."""

    type: str
    content: str
    thread_id: int
    ts: float

    def to_dict(self) -> dict:
        return {"type": self.type, "content": self.content,
                "thread_id": self.thread_id, "ts": self.ts}

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        return cls(type=d["type"], content=d["content"],
                   thread_id=int(d["thread_id"]), ts=float(d["ts"]))
