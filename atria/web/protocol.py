"""WebSocket message type registry and constructors.

Provides a canonical enum of all WebSocket message types used between the
server and the React frontend.  Because ``WSMessageType`` inherits from
``str``, it serializes to the exact same JSON strings the frontend already
expects -- no frontend changes required.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class WSMessageType(str, Enum):
    """All known WebSocket message types."""

    # ── Server → Client ──────────────────────────────────────────────
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    ASK_USER_REQUIRED = "ask_user_required"
    ASK_USER_RESOLVED = "ask_user_resolved"
    PLAN_CONTENT = "plan_content"
    PLAN_APPROVAL_REQUIRED = "plan_approval_required"
    PLAN_APPROVAL_RESOLVED = "plan_approval_resolved"
    STATUS_UPDATE = "status_update"
    TASK_COMPLETED = "task_completed"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_COMPLETE = "subagent_complete"
    PARALLEL_AGENTS_START = "parallel_agents_start"
    PARALLEL_AGENTS_DONE = "parallel_agents_done"
    PARALLEL_SOLVER_STARTED = "parallel_solver_started"
    PARALLEL_SOLVER_PROGRESS = "parallel_solver_progress"
    PARALLEL_SOLVER_DONE = "parallel_solver_done"
    DIVIDE_JOB_STARTED = "divide_job_started"
    DIVIDE_TASK_UPDATE = "divide_task_update"
    DIVIDE_JOB_DONE = "divide_job_done"
    THINKING_BLOCK = "thinking_block"
    PROGRESS = "progress"
    NESTED_TOOL_CALL = "nested_tool_call"
    NESTED_TOOL_RESULT = "nested_tool_result"
    MESSAGE_CHUNK = "message_chunk"
    MESSAGE_START = "message_start"
    MESSAGE_COMPLETE = "message_complete"
    SESSION_ACTIVITY = "session_activity"
    USER_MESSAGE = "user_message"
    MCP_STATUS_CHANGED = "mcp:status_changed"
    MCP_SERVERS_UPDATED = "mcp:servers_updated"
    SEARCH_DONE = "search_done"
    THINKING_TOKEN = "thinking"
    THINKING_DONE = "thinking_done"
    IMAGE_MESSAGE = "image_message"
    DATA_MESSAGE = "data_message"
    CUSTOM_BLOCK = "custom_block"
    CUSTOM_BLOCK_UPDATE = "custom_block_update"
    CUSTOM_BLOCK_REMOVE = "custom_block_remove"
    ERROR = "error"
    PONG = "pong"

    # ── Client → Server ──────────────────────────────────────────────
    QUERY = "query"
    APPROVE = "approve"
    ASK_USER_RESPONSE = "ask_user_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"
    PING = "ping"
    INTERRUPT = "interrupt"


def ws_message(msg_type: WSMessageType, **data: Any) -> dict[str, Any]:
    """Construct a standard WebSocket message envelope.

    Args:
        msg_type: The message type.
        **data: Payload fields placed under the ``"data"`` key.

    Returns:
        ``{"type": "<msg_type>", "data": {**data}}``
    """
    return {"type": msg_type.value, "data": data}
