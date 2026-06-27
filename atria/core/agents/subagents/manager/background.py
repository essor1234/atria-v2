"""Background-execution mixin for SubAgentManager (TaskIQ-backed)."""
from __future__ import annotations

import logging
from typing import Any

from atria.core.tasks.payload import SubagentTaskPayload

logger = logging.getLogger(__name__)


class BackgroundMixin:
    """Adds run_in_background enqueue + collect to SubAgentManager."""

    _task_client: Any  # TaskIQClient | None, set by set_task_client

    def set_task_client(self, client: Any) -> None:
        """Wire a TaskIQClient onto the manager.

        Args:
            client: A TaskIQClient instance (or compatible duck-type).
        """
        self._task_client = client

    def execute_subagent_background(
        self,
        name: str,
        task: str,
        owner_id: str,
        session_id: str,
        working_dir: str,
        config_snapshot: dict[str, Any],
        tool_call_id: str | None = None,
        description: str = "",
        path_mapping: dict[str, str] | None = None,
        docker: bool = False,
        tool_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Enqueue a subagent for background execution via TaskIQ.

        Args:
            name: Subagent type name (e.g. "general-purpose").
            task: The prompt / task description for the subagent.
            owner_id: ID of the user who owns this session.
            session_id: Session ID to associate the background run with.
            working_dir: Filesystem working directory for the subagent.
            config_snapshot: Snapshot of app config (may be unused by worker
                but required by SubagentTaskPayload).
            tool_call_id: Optional parent tool-call ID for tracing.
            description: Human-readable description of the subagent run.
            path_mapping: Optional Docker-path-to-local-path mapping.
            docker: Whether to run the subagent inside Docker.
            tool_names: Explicit list of tool names to allow (None = default).

        Returns:
            Dict with keys: success, background, status, task_id, subagent_type.

        Raises:
            RuntimeError: If no task client has been configured via set_task_client.
        """
        if getattr(self, "_task_client", None) is None:
            raise RuntimeError("Background task client not configured.")
        payload = SubagentTaskPayload(
            session_id=session_id,
            owner_id=owner_id,
            subagent_type=name,
            prompt=task,
            description=description,
            working_dir=working_dir,
            path_mapping=path_mapping or {},
            docker=docker,
            tool_names=tool_names,
            parent_tool_call_id=tool_call_id,
            config_snapshot=config_snapshot,
        )
        task_id = self._task_client.enqueue(payload)
        return {
            "success": True,
            "background": True,
            "status": "running",
            "task_id": task_id,
            "subagent_type": name,
        }

    def get_background_task_output(
        self, task_id: str, block: bool = True, timeout: int = 30000
    ) -> dict[str, Any]:
        """Collect the result of a previously enqueued background subagent.

        Shapes the raw TaskIQClient result for the tool layer:
        - running  → {success: False, status: "running", output: None, task_id}
        - failed / expired → {success: False, status, error, output: None}
        - done     → {success: True, status: "done", output, content, completion_status}

        Args:
            task_id: The task ID returned by execute_subagent_background.
            block: Whether to block until the result is available.
            timeout: Maximum wait time in milliseconds.

        Returns:
            Shaped result dict for the tool layer.
        """
        if getattr(self, "_task_client", None) is None:
            return {
                "success": False,
                "error": "Background task client not configured.",
                "output": None,
            }
        result = self._task_client.await_result(task_id, block=block, timeout_ms=timeout)
        if result.get("status") == "running":
            return {
                "success": False,
                "status": "running",
                "output": None,
                "task_id": task_id,
            }
        if not result.get("success"):
            status = result.get("status", "failed")
            if status == "done":  # task completed but the subagent itself failed
                status = "failed"
            return {
                "success": False,
                "status": status,
                "error": result.get("error") or result.get("content") or "unknown error",
                "output": None,
            }
        return {
            "success": True,
            "status": "done",
            "output": result.get("content", ""),
            "content": result.get("content", ""),
            "completion_status": result.get("completion_status", "success"),
        }
