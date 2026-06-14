"""No-op stub for TaskProgressDisplay — TUI removed, web uses WebSocket for progress."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TaskProgressDisplay:
    """No-op stub. Web UI uses WebSocket for task progress display."""

    def __init__(self, console=None, task_monitor=None) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def print_final_status(self, replacement_message=None) -> None:
        pass
