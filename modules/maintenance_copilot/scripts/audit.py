"""Append-only JSONL audit trail for advisory actions.

Every query, recommendation, validation, and engineer confirmation is appended
with a UTC timestamp so an AI-suggested reference can be traced to the exact
document/revision/page used — the regulatory-traceability requirement.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_LOG_NAME = "audit.log.jsonl"


def default_log_path() -> str:
    """Return MC_AUDIT_LOG if set, else ``<module>/data/audit.log.jsonl``."""
    override = os.environ.get("MC_AUDIT_LOG")
    if override:
        return override
    return str(Path(__file__).resolve().parent.parent / "data" / _LOG_NAME)


def append_event(event: dict, path: str | None = None,
                 now_fn: Callable[[], datetime] | None = None) -> dict:
    """Stamp ``event`` with a UTC ``ts`` and append it as one JSON line.

    Args:
        event: The event payload (not mutated; a stamped copy is written).
        path: Log path; defaults to :func:`default_log_path`.
        now_fn: Clock returning an aware datetime; defaults to ``now(utc)``.

    Returns:
        The stamped event that was written.
    """
    target = Path(path or default_log_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    stamped = {"ts": clock().isoformat(), **event}
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")
    return stamped


def read_events(path: str | None = None) -> list[dict]:
    """Read the JSONL log back into a list (empty if the file is absent)."""
    target = Path(path or default_log_path())
    if not target.is_file():
        return []
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
