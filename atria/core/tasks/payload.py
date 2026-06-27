"""Serializable contract for a background subagent run.

This is the ONLY object that crosses the server→worker boundary. It carries
the *inputs* needed to rebuild dependencies in the worker, never live objects
(mode_manager, tool_registry, etc.), which are not picklable/serializable.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubagentTaskPayload(BaseModel):
    """Everything the worker needs to reconstruct and run a subagent."""

    session_id: str
    owner_id: str
    subagent_type: str
    prompt: str
    description: str = ""
    working_dir: str
    path_mapping: dict[str, str] = Field(default_factory=dict)
    docker: bool = False
    tool_names: list[str] | None = None
    parent_tool_call_id: str | None = None
    config_snapshot: dict[str, Any]
    blackboard_task_id: str | None = None
    thread_id: int = 0
