"""Subagent spawning and background-result collection for the tool registry."""

from __future__ import annotations

import logging
from typing import Any, Union

from atria.db.sync import run_sync

logger = logging.getLogger(__name__)


class SubagentOpsMixin:
    """``spawn_subagent`` / ``get_subagent_output`` handling for ToolRegistry."""

    def _execute_spawn_subagent(
        self,
        arguments: dict[str, Any],
        context: Any = None,
        tool_call_id: Union[str, None] = None,
    ) -> dict[str, Any]:
        """Execute the spawn_subagent tool to spawn a subagent.

        Args:
            arguments: Tool arguments with 'description', 'prompt', and 'subagent_type'
            context: Tool execution context
            tool_call_id: Unique tool call ID for parent context tracking

        Returns:
            Result from subagent execution
        """
        if not self._subagent_manager:
            return {
                "success": False,
                "error": "SubAgentManager not configured. spawn_subagent tool unavailable.",
                "output": None,
            }

        description = arguments.get("description", "")
        # Use 'prompt' as task content, fallback to 'description' for backward compatibility.
        # If 'prompt' key is present (even as empty string), it is the authoritative source —
        # an explicit empty prompt is rejected rather than silently falling back to description.
        prompt_raw = arguments.get("prompt")
        task = prompt_raw if prompt_raw is not None else description
        subagent_type = arguments.get("subagent_type", "general-purpose")

        if not task:
            return {
                "success": False,
                "error": "Task prompt is required for spawn_subagent",
                "output": None,
            }

        strategy = (arguments.get("strategy") or "direct").lower()
        if strategy not in ("direct", "divide", "parallel"):
            return {
                "success": False,
                "error": f"unknown strategy {strategy!r}; expected direct|divide|parallel",
                "output": None,
            }

        if strategy != "direct":
            return self._dispatch_via_orchestrator(strategy, task, subagent_type, context)

        # Create deps from context
        from atria.core.agents.subagents.manager import SubAgentDeps

        deps = SubAgentDeps(
            mode_manager=context.mode_manager if context else None,
            approval_manager=context.approval_manager if context else None,
            undo_manager=context.undo_manager if context else None,
            session_manager=context.session_manager if context else None,
        )

        # Get ui_callback from context for nested tool call display
        ui_callback = context.ui_callback if context else None

        # Get task_monitor from context for interrupt support
        task_monitor = context.task_monitor if context else None

        # Background execution: read the flag and best-effort session identity.
        # ToolExecutionContext exposes no session_id/owner_id directly; pull them
        # from the session manager's current session when available (metadata only —
        # the worker does not reload the session).
        run_in_background = bool(arguments.get("run_in_background", False))
        _sess_mgr = getattr(context, "session_manager", None) if context else None
        _current = getattr(_sess_mgr, "current_session", None) if _sess_mgr else None
        owner_id = (getattr(_current, "owner_id", None) or "") if _current else ""
        session_id = str(getattr(_current, "session_id", "") or "") if _current else ""

        # show_spawn_header=False because react_executor already showed the Spawn[] header
        # via on_tool_call before calling this tool handler
        result = self._subagent_manager.execute_subagent(
            name=subagent_type,
            task=task,
            deps=deps,
            ui_callback=ui_callback,
            task_monitor=task_monitor,
            show_spawn_header=False,
            tool_call_id=tool_call_id,  # Pass for parent context tracking
            run_in_background=run_in_background,
            owner_id=owner_id,
            session_id=session_id,
            config_snapshot={},
        )

        # Background subagent: return the task_id; collection happens later via
        # get_subagent_output. Skip child-session save and shallow-spawn checks
        # (those assume a completed synchronous run).
        if result.get("background"):
            return {
                "success": True,
                "output": (
                    f"[BACKGROUND STARTED] task_id={result['task_id']}. "
                    "Use get_subagent_output(task_id) to collect the result."
                ),
                "task_id": result["task_id"],
                "status": "running",
                "subagent_type": subagent_type,
            }

        # Save subagent conversation as a child session for navigation (Ctrl+G)
        self._save_subagent_session(
            result,
            subagent_type,
            tool_call_id,
            context,
        )

        # Detect shallow subagent completions (≤1 tool call).
        # Spawning a subagent has overhead (extra LLM call + context setup), so if it
        # only made 1 tool call, the parent agent could have done it directly. Inject
        # feedback via _llm_suffix so the LLM learns to avoid trivial spawns.
        subagent_tool_calls = self._count_subagent_tool_calls(result)
        shallow_suffix = ""
        if subagent_tool_calls <= 1 and result.get("success"):
            shallow_suffix = (
                "\n\n[SHALLOW SUBAGENT WARNING] This subagent only made "
                f"{subagent_tool_calls} tool call(s). Spawning a subagent for a task "
                "that requires ≤1 tool call is wasteful — you should have used a "
                "direct tool call instead. For future similar tasks, use read_file, "
                "search, or list_files directly rather than spawning a subagent."
            )

        # Format output for consistency
        if result.get("success"):
            content = result.get("content", "")
            # Always set completion_status for sync subagents (they complete immediately)
            # This helps the LLM understand that results are already included
            completion_status = result.get("completion_status", "success")
            response = {
                "success": True,
                "output": "[SYNC COMPLETE] Subagent finished. Results included below.",
                "separate_response": content,  # Show as separate assistant message
                "subagent_type": subagent_type,
                "completion_status": completion_status,  # Always include for sync completions
            }
            if shallow_suffix:
                response["_llm_suffix"] = shallow_suffix
            return response
        else:
            # Check both "error" and "content" fields for error message
            # MainAgent.run_sync() puts errors in "content", not "error"
            error = result.get("error") or result.get("content") or "Unknown error"
            return {
                "success": False,
                "error": f"[{subagent_type}] {error}",
                "output": None,
                "interrupted": result.get("interrupted", False),  # Propagate interrupt flag
            }

    def _dispatch_via_orchestrator(
        self,
        strategy: str,
        task: str,
        subagent_type_hint: str,
        context: Any,
    ) -> dict[str, Any]:
        """Route the delegation through the divide or parallel orchestrator.

        Args:
            strategy: Either ``"divide"`` or ``"parallel"``.
            task: Natural-language task description for the orchestrator.
            subagent_type_hint: Subagent type label forwarded to the orchestrator.
            context: Tool execution context; may carry ``divide_orchestrator``
                and ``parallel_orchestrator`` attributes (both ``None`` when
                redis/docker is not configured).

        Returns:
            Success dict with ``job_id`` and ``strategy`` on success, or a
            failure dict with a hint to retry with ``strategy="direct"``.
        """
        if strategy == "divide":
            orch = getattr(context, "divide_orchestrator", None)
            if orch is None:
                return {
                    "success": False,
                    "error": (
                        "divide orchestrator not configured (redis unavailable). "
                        'Retry with strategy="direct".'
                    ),
                    "output": None,
                }
            try:
                job_id = orch.start(task, subagent_type_hint, subagent_type_hint)
                rec = orch.collect(job_id)
                summary = rec.get("summary") or rec.get("status") or ""
            except Exception as exc:  # noqa: BLE001 — surface to LLM as tool error
                return {
                    "success": False,
                    "error": f"divide dispatch failed: {exc}",
                    "output": None,
                }
            return {
                "success": True,
                "output": f"[divide {job_id}] {summary}",
                "job_id": job_id,
                "strategy": "divide",
            }

        # strategy == "parallel"
        orch = getattr(context, "parallel_orchestrator", None)
        if orch is None:
            return {
                "success": False,
                "error": (
                    "parallel orchestrator not configured (redis/docker "
                    'unavailable). Retry with strategy="direct".'
                ),
                "output": None,
            }
        try:
            repo_dir = self._get_repo_dir()
            _sess = getattr(context, "session_manager", None)
            _cur = getattr(_sess, "current_session", None) if _sess else None
            owner_id = (getattr(_cur, "owner_id", "") or "") if _cur else ""
            session_id = str(getattr(_cur, "session_id", "") or "") if _cur else ""
            job_id = orch.start(task, 0, repo_dir, owner_id, session_id)
            rec = orch.collect(job_id)
            reasoning = rec.get("reasoning") or ""
            applied = rec.get("applied")
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "error": f"parallel dispatch failed: {exc}",
                "output": None,
            }
        return {
            "success": True,
            "output": f"[parallel {job_id}] applied={applied} — {reasoning}",
            "job_id": job_id,
            "strategy": "parallel",
        }

    @staticmethod
    def _count_subagent_tool_calls(result: dict[str, Any]) -> int:
        """Count actual tool calls made by a subagent from its message history.

        Counts assistant messages that contain tool_calls, which represents
        the number of LLM turns where tools were invoked. This is more
        accurate than counting tool result messages since one turn can
        invoke multiple parallel tools.
        """
        messages = result.get("messages", [])
        return sum(
            1 for msg in messages if msg.get("role") == "assistant" and msg.get("tool_calls")
        )

    def _save_subagent_session(
        self,
        result: dict[str, Any],
        subagent_type: str,
        tool_call_id: Union[str, None],
        context: Any,
    ) -> None:
        """Save subagent conversation as a child session and record mapping.

        Creates a new session from the subagent's messages and stores a
        tool_call_id -> child_session_id mapping in the parent session's
        subagent_sessions field for later navigation (Ctrl+G).

        Args:
            result: Result dict from execute_subagent (contains 'messages')
            subagent_type: Name of the subagent type
            tool_call_id: Tool call ID from the parent context
            context: Tool execution context with session_manager
        """
        if tool_call_id is None:
            return

        subagent_messages = result.get("messages")
        if not subagent_messages:
            return

        session_manager = getattr(context, "session_manager", None) if context else None
        if session_manager is None:
            return

        parent_session = run_sync(session_manager.get_current_session())
        if parent_session is None:
            return

        try:
            from atria.models.message import ChatMessage, Role
            from atria.models.session import Session

            # Create a child session for the subagent conversation
            child_session = Session(
                working_directory=parent_session.working_directory,
                parent_id=parent_session.id,
                metadata={"title": f"Subagent: {subagent_type}"},
            )

            # Convert raw message dicts to ChatMessage objects
            valid_roles = {r.value for r in Role}
            for msg in subagent_messages:
                if isinstance(msg, dict):
                    role_str = msg.get("role", "user")
                    content = msg.get("content", "")
                    # Skip system and tool messages (prompt and tool results)
                    if role_str not in valid_roles or role_str == "system":
                        continue
                    child_session.add_message(
                        ChatMessage(role=Role(role_str), content=str(content) if content else "")
                    )

            # Save child session
            run_sync(session_manager.save_session(child_session))

            # Record mapping in parent session
            if not hasattr(parent_session, "subagent_sessions"):
                parent_session.subagent_sessions = {}
            parent_session.subagent_sessions[tool_call_id] = child_session.id
            run_sync(session_manager.save_session(parent_session))
        except Exception:
            # Non-critical — don't break subagent execution if session save fails
            logger.debug("Failed to save subagent session", exc_info=True)

    def _get_subagent_output(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Get output from a background subagent task.

        Args:
            arguments: Tool arguments with 'task_id', optional 'block' and 'timeout'
            context: Tool execution context

        Returns:
            Result from background subagent or status information
        """
        task_id = arguments.get("task_id", "")
        block = arguments.get("block", True)
        timeout = arguments.get("timeout", 30000)

        if not task_id:
            return {
                "success": False,
                "error": "task_id is required",
                "output": None,
            }

        if not self._subagent_manager:
            return {
                "success": False,
                "error": "SubAgentManager not configured",
                "output": None,
            }

        # Check if manager has background task support
        if hasattr(self._subagent_manager, "get_background_task_output"):
            return self._subagent_manager.get_background_task_output(
                task_id, block=block, timeout=timeout
            )

        # Fallback for managers without background support
        return {
            "success": False,
            "error": f"Background task support not available. Task ID '{task_id}' not found.",
            "output": "Background subagent execution is not yet fully implemented. "
            "Subagents currently run synchronously.",
        }

    def _get_repo_dir(self) -> str:
        """Return the run's repo/working directory, defaulting to '.'."""
        return (
            str(self.file_ops.working_dir)
            if self.file_ops and getattr(self.file_ops, "working_dir", None)
            else "."
        )
