"""Single-tool and parallel tool execution for ReactExecutor."""

from __future__ import annotations

import json
import logging
from concurrent.futures import as_completed
from typing import Dict

from atria.core.runtime.monitoring import TaskMonitor
from atria.core.utils.tool_display import format_tool_call

from ._debug import _session_debug

logger = logging.getLogger(__name__)


class ToolExecutionMixin:
    """Executes individual tool calls, quietly or in parallel."""

    def _execute_single_tool(
        self, tool_call: dict, ctx, suppress_separate_response: bool = False
    ) -> dict:
        """Execute a single tool and handle UI updates.

        Args:
            tool_call: The tool call dict from LLM response
            ctx: Iteration context with registry, callbacks, etc.
            suppress_separate_response: If True, don't display separate_response immediately.
                Used in parallel mode to aggregate responses later.
        """
        tool_name = tool_call["function"]["name"]

        if tool_name == "task_complete":
            return {}

        # Debug
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_debug"):
            ctx.ui_callback.on_debug(f"Executing tool: {tool_name}", "TOOL")

        args_str = tool_call["function"]["arguments"]
        _session_debug().log(
            "tool_call_start", "tool", name=tool_name, params_preview=args_str[:200]
        )

        # Notify UI call
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_tool_call"):
            ctx.ui_callback.on_tool_call(tool_name, args_str)

        # Execute
        import time as _time

        tool_start = _time.monotonic()
        try:
            result = self._execute_tool_call(
                tool_call,
                ctx.tool_registry,
                ctx.approval_manager,
                ctx.undo_manager,
                ui_callback=ctx.ui_callback,
            )
        except Exception as exc:
            import traceback

            _session_debug().log(
                "tool_call_error",
                "tool",
                name=tool_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raise
        tool_duration_ms = int((_time.monotonic() - tool_start) * 1000)

        _preview_src = result.get("output") or result.get("error") or ""
        if not isinstance(_preview_src, str):
            _preview_src = str(_preview_src)
        result_preview = _preview_src[:200]
        _session_debug().log(
            "tool_call_end",
            "tool",
            name=tool_name,
            duration_ms=tool_duration_ms,
            success=result.get("success", False),
            result_preview=result_preview,
        )

        # Store summary
        self._last_operation_summary = format_tool_call(tool_name, json.loads(args_str))

        # Notify UI result
        if ctx.ui_callback and hasattr(ctx.ui_callback, "on_tool_result"):
            ctx.ui_callback.on_tool_result(tool_name, args_str, result)

        # Handle subagent display (suppress in parallel mode for aggregation)
        separate_response = result.get("separate_response")
        if separate_response and not suppress_separate_response:
            self._display_message(separate_response, ctx.ui_callback)

        return result

    def _execute_tool_quietly(self, tool_call: dict, ctx) -> dict:
        """Execute a tool without UI notifications (for silent parallel mode).

        Skips on_tool_call/on_tool_result callbacks and spinner display.
        Keeps debug logging and interrupt support.
        """
        import time as _time
        import traceback

        tool_name = tool_call["function"]["name"]
        if tool_name == "task_complete":
            return {}

        tool_args = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]
        args_str = tool_call["function"]["arguments"]
        _session_debug().log(
            "tool_call_start", "tool", name=tool_name, params_preview=args_str[:200]
        )

        tool_monitor = TaskMonitor()
        if self._active_interrupt_token:
            tool_monitor.set_interrupt_token(self._active_interrupt_token)

        tool_start = _time.monotonic()
        try:
            result = ctx.tool_registry.execute_tool(
                tool_name,
                tool_args,
                mode_manager=self._mode_manager,
                approval_manager=ctx.approval_manager,
                undo_manager=ctx.undo_manager,
                task_monitor=tool_monitor,
                session_manager=self.session_manager,
                ui_callback=ctx.ui_callback,
                tool_call_id=tool_call_id,
                blackboard=getattr(self, "_blackboard_handle", None),
            )
        except Exception as exc:
            if isinstance(exc, InterruptedError):
                raise
            _session_debug().log(
                "tool_call_error",
                "tool",
                name=tool_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            return {"success": False, "error": str(exc)}

        tool_duration_ms = int((_time.monotonic() - tool_start) * 1000)
        _preview_src = result.get("output") or result.get("error") or ""
        if not isinstance(_preview_src, str):
            _preview_src = str(_preview_src)
        result_preview = _preview_src[:200]
        _session_debug().log(
            "tool_call_end",
            "tool",
            name=tool_name,
            duration_ms=tool_duration_ms,
            success=result.get("success", False),
            result_preview=result_preview,
        )
        return result

    def _execute_tools_parallel(self, tool_calls: list, ctx) -> tuple[Dict[str, dict], bool]:
        """Execute tools in parallel using managed thread pool.

        Uses `with` statement to ensure executor cleanup (no memory leaks).
        ThreadPoolExecutor's max_workers naturally limits concurrency.

        Args:
            tool_calls: List of tool call dicts from LLM response
            ctx: Iteration context with registry, callbacks, etc.

        Returns:
            Tuple of (results_by_id dict, operation_cancelled bool)
        """
        tool_results_by_id: Dict[str, dict] = {}
        operation_cancelled = False
        ui_callback = ctx.ui_callback

        # Check if ALL tools are spawn_subagent (parallel agent scenario)
        spawn_calls = [tc for tc in tool_calls if tc["function"]["name"] == "spawn_subagent"]
        is_parallel_agents = len(spawn_calls) == len(tool_calls) and len(spawn_calls) > 1

        # Build agent info mapping (tool_call_id -> agent info)
        # Pass full agent info to UI for individual agent tracking
        agent_name_map: Dict[str, str] = {}
        if is_parallel_agents and ui_callback:
            # Collect full agent info for each parallel agent
            agent_infos: list[dict] = []
            for tc in spawn_calls:
                args = json.loads(tc["function"]["arguments"])
                agent_type = args.get("subagent_type", "Agent")
                description = args.get("description", "")
                tool_call_id = tc["id"]
                # Map tool_call_id to base type (for completion tracking)
                agent_name_map[tool_call_id] = agent_type
                # Collect full info for UI display
                agent_infos.append(
                    {
                        "agent_type": agent_type,
                        "description": description,
                        "tool_call_id": tool_call_id,
                    }
                )
            if hasattr(ui_callback, "on_parallel_agents_start"):
                import sys

                print(
                    f"[DEBUG] on_parallel_agents_start with agent_infos={agent_infos}",
                    file=sys.stderr,
                )
                ui_callback.on_parallel_agents_start(agent_infos)

        # Check interrupt before launching parallel execution
        if self._active_interrupt_token and self._active_interrupt_token.is_requested():
            for tc in tool_calls:
                tool_results_by_id[tc["id"]] = {
                    "success": False,
                    "error": "Interrupted by user",
                    "output": None,
                    "interrupted": True,
                }
            return tool_results_by_id, True

        executor = self._parallel_executor

        if is_parallel_agents:
            # --- Existing subagent path (with per-agent UI tracking) ---
            future_to_call = {
                executor.submit(
                    self._execute_single_tool,
                    tc,
                    ctx,
                    suppress_separate_response=True,
                ): tc
                for tc in tool_calls
            }

            for future in as_completed(future_to_call):
                tool_call = future_to_call[future]
                try:
                    result = future.result()
                except InterruptedError:
                    result = {"success": False, "error": "Interrupted by user", "interrupted": True}
                except Exception as e:
                    result = {"success": False, "error": str(e)}

                tool_results_by_id[tool_call["id"]] = result
                if result.get("interrupted"):
                    operation_cancelled = True

                # Track individual agent completion
                if ui_callback:
                    tool_name = tool_call["function"]["name"]
                    if tool_name == "spawn_subagent":
                        tool_call_id = tool_call["id"]
                        success = result.get("success", True) if isinstance(result, dict) else True
                        if hasattr(ui_callback, "on_parallel_agent_complete"):
                            ui_callback.on_parallel_agent_complete(tool_call_id, success)

            # Notify UI that all parallel agents are done
            if ui_callback and hasattr(ui_callback, "on_parallel_agents_done"):
                ui_callback.on_parallel_agents_done()

        else:
            # --- Silent parallel: execute concurrently, display sequentially ---
            future_to_call = {
                executor.submit(self._execute_tool_quietly, tc, ctx): tc for tc in tool_calls
            }
            for future in as_completed(future_to_call):
                tool_call = future_to_call[future]
                try:
                    result = future.result()
                except InterruptedError:
                    result = {"success": False, "error": "Interrupted by user", "interrupted": True}
                except Exception as e:
                    result = {"success": False, "error": str(e)}
                tool_results_by_id[tool_call["id"]] = result
                if result.get("interrupted"):
                    operation_cancelled = True

            # Replay display in original order (looks sequential to user)
            for tc in tool_calls:
                result = tool_results_by_id.get(tc["id"], {})
                tool_name = tc["function"]["name"]
                args_str = tc["function"]["arguments"]
                self._last_operation_summary = format_tool_call(tool_name, json.loads(args_str))
                if ui_callback and hasattr(ui_callback, "on_tool_call"):
                    ui_callback.on_tool_call(tool_name, args_str)
                if ui_callback and hasattr(ui_callback, "on_tool_result"):
                    ui_callback.on_tool_result(tool_name, args_str, result)

        return tool_results_by_id, operation_cancelled
