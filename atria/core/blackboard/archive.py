"""Best-effort Postgres archive of a task's final blackboard (inspection only)."""
from __future__ import annotations

import logging
from typing import Callable

from atria.core.blackboard.models import Note

logger = logging.getLogger(__name__)


async def archive_to_postgres(
    session_factory: Callable[[], object],
    task_id: str,
    owner_id: str,
    notes: list[Note],
) -> int:
    """Insert one row per note. Returns rows written; 0 on any failure (never raises).

    Args:
        session_factory: Callable returning an async session context manager
            (the same one pg_manager uses).
        task_id: The task whose blackboard this is.
        owner_id: Owner/user id for the run.
        notes: Final blackboard notes to archive.
    """
    if not notes:
        return 0
    try:
        from atria.db.models import BlackboardNote

        session = session_factory()
        async with session as s:
            for n in notes:
                s.add(
                    BlackboardNote(
                        task_id=task_id,
                        owner_id=owner_id,
                        thread_id=n.thread_id,
                        type=n.type,
                        content=n.content,
                        ts=n.ts,
                    )
                )
            await s.commit()
        return len(notes)
    except Exception as exc:  # noqa: BLE001 — archive is best-effort
        logger.warning("blackboard archive failed for %s: %s", task_id, exc)
        return 0
