"""Tool-result history handling and large-output offloading for ReactExecutor."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from atria.core.runtime.monitoring import TaskMonitor
from atria.db.sync import run_sync
from atria.core.utils.tool_display import format_tool_call

from ._debug import _ctx_logger

logger = logging.getLogger(__name__)


class ToolResultsMixin:
    """Records tool results into history and offloads oversized outputs."""

    def _add_tool_result_to_history(
        self,
        messages: list,
        tool_call: dict,
        result: dict,
        *,
        has_subagent_tool: bool = False,
    ):
        """Add tool execution result to message history.

        Large outputs (>8000 chars) are offloaded to scratch files and replaced
        with a summary + file reference, preventing context bloat.
        """
        tool_name = tool_call["function"]["name"]

        separate_response = result.get("separate_response")
        completion_status = result.get("completion_status")

        if result.get("success", False):
            tool_result = separate_response if separate_response else result.get("output", "")
            if completion_status:
                tool_result = f"[completion_status={completion_status}]\n{tool_result}"
        else:
            tool_result = f"Error in {tool_name}: {result.get('error', 'Tool execution failed')}"

        # Offload large outputs to scratch files
        tool_result = self._maybe_offload_output(
            tool_name,
            tool_call["id"],
            tool_result,
            has_subagent_tool=has_subagent_tool,
        )

        _ctx_logger.info(
            "tool_result_added: tool=%s content_len=%d",
            tool_name,
            len(tool_result) if tool_result else 0,
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result,
            }
        )

    def _maybe_offload_output(
        self,
        tool_name: str,
        tool_call_id: str,
        output: str,
        *,
        has_subagent_tool: bool = False,
    ) -> str:
        """Offload large tool output to a scratch file, return summary + ref.

        Tool outputs are ~80% of context token usage. Writing outputs >8000 chars
        to scratch files and replacing them with a summary + file reference
        dramatically reduces context consumption.

        Args:
            tool_name: Name of the tool.
            tool_call_id: Unique tool call ID for the filename.
            output: Full tool output string.
            has_subagent_tool: Whether the current agent can spawn subagents.

        Returns:
            Original output if small enough, or summary + file reference.
        """
        if not output or len(output) <= self.OFFLOAD_THRESHOLD:
            return output

        # Don't offload subagent results or completion status messages
        if "[completion_status=" in output or "[SYNC COMPLETE]" in output:
            return output

        # Determine session ID for file path
        session = run_sync(self.session_manager.get_current_session())
        session_id = session.id if session else "unknown"
        scratch_dir = Path.home() / ".atria" / "scratch" / session_id

        try:
            scratch_dir.mkdir(parents=True, exist_ok=True)
            # Use tool name + truncated call ID for readable filenames
            safe_name = tool_name.replace("/", "_")
            short_id = tool_call_id[:8] if tool_call_id else "unknown"
            scratch_path = scratch_dir / f"{safe_name}_{short_id}.txt"
            scratch_path.write_text(output, encoding="utf-8")

            # Build summary: keep first 500 chars for immediate context
            line_count = output.count("\n") + 1
            char_count = len(output)
            preview = output[:500]
            if len(output) > 500:
                preview += "\n..."

            # Dynamic truncation hint based on agent capabilities
            if has_subagent_tool:
                hint = (
                    "Delegate to an explore subagent to process the full output via "
                    "search/read_file, or use read_file with offset/max_lines to page through it."
                )
            else:
                hint = "Use read_file with offset/max_lines to page through the full output."

            return (
                f"{preview}\n\n"
                f"[Output offloaded: {line_count} lines, {char_count} chars → "
                f"`{scratch_path}`]\n"
                f"{hint}"
            )
        except OSError:
            logger.debug("Failed to offload tool output to scratch file", exc_info=True)
            return output

    def _execute_tool_call(
        self,
        tool_call: dict,
        tool_registry,
        approval_manager,
        undo_manager,
        ui_callback=None,
    ) -> dict:
        """Execute a single tool call."""
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]
        tool_call_display = format_tool_call(tool_name, tool_args)

        tool_monitor = TaskMonitor()
        if self._active_interrupt_token:
            tool_monitor.set_interrupt_token(self._active_interrupt_token)
        tool_monitor.start(tool_call_display, initial_tokens=0)

        if self._tool_executor:
            self._tool_executor._current_task_monitor = tool_monitor

        progress = None
        if self.console:
            from atria.ui_textual.components.task_progress import TaskProgressDisplay

            progress = TaskProgressDisplay(self.console, tool_monitor)
            progress.start()

        try:
            result = tool_registry.execute_tool(
                tool_name,
                tool_args,
                mode_manager=self._mode_manager,
                approval_manager=approval_manager,
                undo_manager=undo_manager,
                task_monitor=tool_monitor,
                session_manager=self.session_manager,
                ui_callback=ui_callback,
                tool_call_id=tool_call_id,  # Pass for subagent parent tracking
                blackboard=getattr(self, "_blackboard_handle", None),
            )
            return result
        finally:
            if progress:
                progress.stop()
            if self._tool_executor:
                self._tool_executor._current_task_monitor = None
