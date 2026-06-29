"""Artifact index: tracks files touched during a session, surviving compaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ArtifactIndex:
    """Tracks files touched during a session, surviving compaction.

    Records file operations (create, modify, read, delete) with metadata
    so the agent retains awareness of workspace state post-compaction.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def record(
        self,
        file_path: str,
        operation: str,
        details: str = "",
    ) -> None:
        """Record a file operation.

        Args:
            file_path: Absolute or relative file path.
            operation: One of "created", "modified", "read", "deleted".
            details: Optional details (line count, key functions, etc.).
        """
        normalized = str(file_path)
        existing = self._entries.get(normalized)
        now = datetime.now().isoformat()

        if existing:
            existing["last_operation"] = operation
            existing["last_details"] = details
            existing["updated_at"] = now
            existing["operation_count"] = existing.get("operation_count", 1) + 1
            if operation not in existing.get("operations_seen", []):
                existing["operations_seen"].append(operation)
        else:
            self._entries[normalized] = {
                "file_path": normalized,
                "last_operation": operation,
                "last_details": details,
                "created_at": now,
                "updated_at": now,
                "operation_count": 1,
                "operations_seen": [operation],
            }

    def as_summary(self) -> str:
        """Format the artifact index as a compact summary for injection into compaction."""
        if not self._entries:
            return ""

        lines = ["## Artifact Index (files touched this session)"]
        for path, entry in self._entries.items():
            ops = ", ".join(entry["operations_seen"])
            detail = f" — {entry['last_details']}" if entry["last_details"] else ""
            lines.append(f"- `{path}` [{ops}]{detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for session persistence."""
        return {"entries": dict(self._entries)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactIndex:
        """Deserialize from session data."""
        idx = cls()
        idx._entries = dict(data.get("entries", {}))
        return idx

    def __len__(self) -> int:
        return len(self._entries)
