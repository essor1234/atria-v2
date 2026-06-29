"""Tool call processing, execution, and result handling for ReactExecutor."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ._debug import _ctx_logger, _debug_log, _session_debug
from ._tool_execution import ToolExecutionMixin
from ._tool_results import ToolResultsMixin

logger = logging.getLogger(__name__)


class ToolProcessingMixin(ToolExecutionMixin, ToolResultsMixin):
    """Mixin providing tool call processing, execution, and result handling.

    Expects the host class to provide:
        - self._active_interrupt_token
        - self._tool_executor
        - self._llm_caller
        - self._cost_tracker
        - self._compactor
        - self._snapshot_manager
        - self._parallel_executor
        - self._injection_queue
        - self._last_operation_summary
        - self.session_manager
        - self.config
        - self.console
        - self.READ_OPERATIONS
        - self.PARALLELIZABLE_TOOLS
        - self.MAX_NUDGE_ATTEMPTS
        - self.MAX_TODO_NUDGES
        - self.OFFLOAD_THRESHOLD
    """

    def _process_tool_calls(self, ctx, tool_calls: list, content: str, raw_content: Optional[str]):
        """Process a list of tool calls."""
        from atria.core.agents.prompts import get_reminder
        from atria.core.agents.prompts.reminders import append_nudge

        # Import LoopAction locally to avoid circular imports
        from atria.repl.react_executor.executor import LoopAction

        # Reset no-tool-call counter
        ctx.consecutive_no_tool_calls = 0

        # Doom-loop detection: auto-recover with escalating nudges
        doom_warning = self._detect_doom_loop(tool_calls, ctx)
        if doom_warning:
            ctx.doom_loop_nudge_count += 1
            _debug_log(f"[DOOM_LOOP] nudge_count={ctx.doom_loop_nudge_count}: {doom_warning}")

            if ctx.doom_loop_nudge_count >= 3:
                # Third strike — force stop
                if ctx.ui_callback and hasattr(ctx.ui_callback, "on_message"):
                    ctx.ui_callback.on_message(
                        f"Agent stuck in loop after multiple recovery attempts. "
                        f"Stopping. {doom_warning}"
                    )
                ctx.messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"[SYSTEM] {doom_warning}\n"
                            "You have been stuck in a loop despite multiple warnings. "
                            "STOP and explain what you're trying to do."
                        ),
                    }
                )
                ctx.recent_tool_calls.clear()
                return LoopAction.BREAK

            if ctx.doom_loop_nudge_count == 2:
                # Second nudge — notify user silently (no blocking prompt)
                if ctx.ui_callback and hasattr(ctx.ui_callback, "on_message"):
                    ctx.ui_callback.on_message(f"Agent may be stuck: {doom_warning}")

            # Inject guidance (first and second nudge)
            ctx.messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[SYSTEM WARNING] {doom_warning}\n"
                        "You appear to be repeating the same action without progress. "
                        "Please try a completely different approach or explain what "
                        "you're trying to accomplish so we can find a better path."
                    ),
                }
            )
            ctx.recent_tool_calls.clear()
            return LoopAction.CONTINUE

        # Check for task completion FIRST (before displaying content)
        # This prevents duplicate bullets (one for content, one for summary)
        task_complete_call = next(
            (tc for tc in tool_calls if tc["function"]["name"] == "task_complete"), None
        )
        if task_complete_call:
            args = json.loads(task_complete_call["function"]["arguments"])
            summary = args.get("summary", "Task completed")
            status = args.get("status", "success")

            # Block completion if todos are incomplete (ported from main_agent.py)
            if status == "success":
                todo_handler = getattr(ctx.tool_registry, "todo_handler", None)
                if todo_handler and todo_handler.has_incomplete_todos():
                    if ctx.todo_nudge_count < self.MAX_TODO_NUDGES:
                        ctx.todo_nudge_count += 1
                        incomplete = todo_handler.get_incomplete_todos()
                        titles = [t.title for t in incomplete[:3]]
                        nudge = get_reminder(
                            "incomplete_todos_nudge",
                            count=str(len(incomplete)),
                            todo_list="\n".join(f"  - {t}" for t in titles),
                        )
                        ctx.messages.append({"role": "assistant", "content": summary})
                        append_nudge(ctx.messages, nudge)
                        return LoopAction.CONTINUE

            # Check injection queue before accepting task_complete
            if not self._injection_queue.empty():
                _debug_log("[INJECT] task_complete deferred: new user messages in queue")
                ctx.messages.append({"role": "assistant", "content": summary})
                self._display_message(summary, ctx.ui_callback)
                return LoopAction.CONTINUE

            self._display_message(summary, ctx.ui_callback, dim=True)
            self._add_assistant_message(summary, raw_content)
            return LoopAction.BREAK

        # Display thinking (only when NOT task_complete)
        if content:
            self._display_message(content, ctx.ui_callback)

        # Add assistant message to history
        ctx.messages.append(
            {
                "role": "assistant",
                "content": raw_content,
                "tool_calls": tool_calls,
            }
        )

        # Track reads for nudging
        all_reads = all(tc["function"]["name"] in self.READ_OPERATIONS for tc in tool_calls)
        ctx.consecutive_reads = ctx.consecutive_reads + 1 if all_reads else 0

        # Explore-first enforcement: block excessive exploration reads
        # Skip after plan approval — the planning phase already explored the codebase
        if (
            not ctx.has_explored
            and not ctx.plan_approved_signal_injected
            and all_reads
            and ctx.consecutive_reads >= 3
        ):
            # Block execution — tell agent to use Code-Explorer instead
            for tc in tool_calls:
                append_nudge(
                    ctx.messages,
                    get_reminder("explore_delegate_nudge"),
                    role="tool",
                    tool_call_id=tc["id"],
                )
            ctx.consecutive_reads = 0
            ctx.skip_next_thinking = True
            return LoopAction.CONTINUE

        # Explore-first enforcement: block task subagent spawns until Code-Explorer has run
        EXPLORE_EXEMPT_SUBAGENTS = {"Code-Explorer", "ask-user"}
        if not ctx.has_explored and not ctx.plan_approved_signal_injected:
            for tc in tool_calls:
                if tc["function"]["name"] == "spawn_subagent":
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        continue
                    subagent_type = args.get("subagent_type", "")
                    if subagent_type not in EXPLORE_EXEMPT_SUBAGENTS:
                        # Nudge the agent to explore first
                        append_nudge(
                            ctx.messages,
                            get_reminder("explore_first_nudge"),
                            role="tool",
                            tool_call_id=tc["id"],
                        )
                        # Fill remaining tool calls with synthetic results
                        for other_tc in tool_calls:
                            if other_tc["id"] != tc["id"]:
                                append_nudge(
                                    ctx.messages,
                                    "Blocked: explore first.",
                                    role="tool",
                                    tool_call_id=other_tc["id"],
                                )
                        ctx.skip_next_thinking = True
                        return LoopAction.CONTINUE

        # Mark explored / planner spawned
        for tc in tool_calls:
            if tc["function"]["name"] == "spawn_subagent":
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    continue
                subagent_type = args.get("subagent_type", "")
                if subagent_type == "Code-Explorer":
                    ctx.has_explored = True
                elif subagent_type == "Planner":
                    ctx.planner_pending = True
                    ctx.planner_plan_path = args.get("plan_file_path", "")

        # Execute tools (parallel for spawn_subagent batches or read-only batches)
        spawn_calls = [tc for tc in tool_calls if tc["function"]["name"] == "spawn_subagent"]
        is_all_spawn_agents = len(spawn_calls) == len(tool_calls) and len(spawn_calls) > 1
        is_all_parallelizable = len(tool_calls) > 1 and all(
            tc["function"]["name"] in self.PARALLELIZABLE_TOOLS for tc in tool_calls
        )

        tool_denied = False
        if is_all_spawn_agents or is_all_parallelizable:
            # Parallel execution: subagent batches or read-only tool batches
            tool_results_by_id, operation_cancelled = self._execute_tools_parallel(tool_calls, ctx)
        else:
            # Sequential execution for all other tool calls
            tool_results_by_id = {}
            operation_cancelled = False
            for tool_call in tool_calls:
                # Check interrupt BEFORE executing the next tool (Fix 6)
                if self._active_interrupt_token and self._active_interrupt_token.is_requested():
                    tool_results_by_id[tool_call["id"]] = {
                        "success": False,
                        "error": "Interrupted by user",
                        "output": None,
                        "interrupted": True,
                    }
                    operation_cancelled = True
                    break

                result = self._execute_single_tool(tool_call, ctx)
                tool_results_by_id[tool_call["id"]] = result
                if result.get("interrupted", False):
                    if result.get("denied", False):
                        tool_denied = True
                    else:
                        operation_cancelled = True
                    break

        # Guard: ensure every tool_call has a result (fills missing with synthetic errors)
        from atria.core.context_engineering.message_pair_validator import (
            MessagePairValidator,
        )

        tool_results_by_id = MessagePairValidator.validate_tool_results_complete(
            tool_calls, tool_results_by_id
        )

        # Snapshot tracking: capture state after write operations
        if self._snapshot_manager and not operation_cancelled:
            _write_tools = {"write_file", "edit_file", "run_command"}
            has_writes = any(tc["function"]["name"] in _write_tools for tc in tool_calls)
            if has_writes:
                self._snapshot_manager.track()

        # Check if agent has subagent capability (for dynamic truncation hints)
        _has_subagent = "spawn_subagent" in getattr(ctx.tool_registry, "_handlers", {})

        # Batch add all results after completion (maintains message order)
        for tool_call in tool_calls:
            self._add_tool_result_to_history(
                ctx.messages,
                tool_call,
                tool_results_by_id[tool_call["id"]],
                has_subagent_tool=_has_subagent,
            )

        # Inject plan execution signal after plan approval
        for tool_call in tool_calls:
            if tool_call["function"]["name"] == "present_plan":
                tc_result = tool_results_by_id.get(tool_call["id"], {})
                if tc_result.get("plan_approved") and not ctx.plan_approved_signal_injected:
                    ctx.plan_approved_signal_injected = True
                    todos_created = tc_result.get("todos_created", 0)
                    plan_content = tc_result.get("plan_content", "")
                    ctx.messages.append(
                        {
                            "role": "user",
                            "content": get_reminder(
                                "plan_approved_signal",
                                todos_created=str(todos_created),
                                plan_content=plan_content,
                            ),
                        }
                    )
                    break

        # Auto-complete when a background task was queued.
        # Breaks the loop immediately — agent must NOT continue searching.
        for tool_call in tool_calls:
            tc_result = tool_results_by_id.get(tool_call["id"], {})
            if tc_result.get("_bg_task_started"):
                bg_summary = tc_result.get("_bg_summary", "Background task started.")
                self._add_assistant_message(bg_summary, bg_summary)
                self._display_message(bg_summary, ctx.ui_callback, dim=True)
                _debug_log("[BG_TASK] Background task started — breaking loop")
                return LoopAction.BREAK

        # Nudge agent to finish when all todos are done (at most once)
        if not ctx.all_todos_complete_nudged:
            todo_handler = getattr(ctx.tool_registry, "todo_handler", None)
            if (
                todo_handler
                and todo_handler.has_todos()
                and not todo_handler.has_incomplete_todos()
            ):
                ctx.all_todos_complete_nudged = True
                append_nudge(ctx.messages, get_reminder("all_todos_complete_nudge"))

        # Update context usage indicator after tool results are added
        if self._compactor:
            _ctx_logger.info("context_usage_after_tools: msg_count=%d", len(ctx.messages))
            _session_debug().log(
                "context_usage_after_tools",
                "compaction",
                message_count=len(ctx.messages),
            )
            self._compactor.should_compact(ctx.messages, ctx.agent.system_prompt)
            self._push_context_usage(ctx)

        if operation_cancelled:
            return LoopAction.BREAK

        if tool_denied:
            append_nudge(ctx.messages, get_reminder("tool_denied_nudge"))

        # Persist and Learn
        _debug_log("[TOOLS] Before _persist_step")
        self._persist_step(ctx, tool_calls, tool_results_by_id, content, raw_content)
        _debug_log("[TOOLS] After _persist_step")

        # Check nudge for reads
        if self._should_nudge_agent(ctx.consecutive_reads, ctx.messages):
            ctx.consecutive_reads = 0

        _debug_log("[TOOLS] Returning LoopAction.CONTINUE")
        return LoopAction.CONTINUE
