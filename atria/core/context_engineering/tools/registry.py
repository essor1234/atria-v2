"""Primary tool registry implementation coordinating handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union, TYPE_CHECKING

from atria.core.context_engineering.tools.context import ToolExecutionContext
from atria.core.paths import get_paths
from atria.core.skill_tools import SkillToolContext, SkillToolLoader, ToolSpec
import logging

if TYPE_CHECKING:
    from atria.core.hooks.manager import HookManager

from atria.core.context_engineering.tools.handlers.file_handlers import FileToolHandler
from atria.core.context_engineering.mcp.handler import McpToolHandler
from atria.core.context_engineering.tools.handlers.process_handlers import ProcessToolHandler
from atria.core.context_engineering.tools.handlers.web_handlers import WebToolHandler
from atria.core.context_engineering.tools.handlers.web_search_handler import WebSearchHandler
from atria.core.context_engineering.tools.handlers.notebook_edit_handler import (
    NotebookEditHandler,
)
from atria.core.context_engineering.tools.handlers.ask_user_handler import AskUserHandler
from atria.core.context_engineering.tools.handlers.screenshot_handler import ScreenshotToolHandler
from atria.core.context_engineering.tools.handlers.todo_handler import TodoHandler
from atria.core.context_engineering.tools.handlers.thinking_handler import ThinkingHandler
from atria.core.context_engineering.tools.handlers.search_tools_handler import SearchToolsHandler
from atria.core.context_engineering.tools.handlers.batch_handler import BatchToolHandler
from atria.core.context_engineering.tools.implementations.note_tool import execute_note
from atria.core.context_engineering.tools.handlers.memory_handlers import MemoryToolHandler
from atria.core.context_engineering.tools.handlers.session_handlers import SessionToolHandler
from atria.core.context_engineering.tools.handlers.browser_handlers import BrowserToolHandler
from atria.core.context_engineering.tools.handlers.schedule_handlers import ScheduleToolHandler
from atria.core.context_engineering.tools.handlers.message_handlers import MessageToolHandler
from atria.core.context_engineering.tools.implementations.send_image_tool import SendImageHandler
from atria.core.context_engineering.tools.implementations.render_component_tool import (
    RenderComponentHandler,
)
from atria.core.context_engineering.tools.implementations.md_to_pdf_tool import (
    MarkdownToPdfHandler,
)
from atria.core.context_engineering.tools.handlers.md_to_pdf_handler import MdToPdfHandler
from atria.core.context_engineering.tools.implementations.md_to_pdf_tool import MdToPdfTool
from atria.core.context_engineering.tools.handlers.artifacts_handler import ArtifactsToolHandler

if TYPE_CHECKING:
    from atria.core.skills import SkillLoader

logger = logging.getLogger(__name__)

from atria.core.context_engineering.tools.implementations.agents_tool import AgentsTool
from atria.core.context_engineering.tools.implementations.patch_tool import PatchTool
from atria.core.context_engineering.tools.implementations.pdf_tool import PDFTool
from atria.core.context_engineering.tools.implementations.task_complete_tool import (
    TaskCompleteTool,
)
from atria.core.context_engineering.tools.implementations.present_plan_tool import (
    PresentPlanTool,
)
from atria.core.context_engineering.tools.symbol_tools import (
    handle_find_symbol,
    handle_find_referencing_symbols,
    handle_insert_before_symbol,
    handle_insert_after_symbol,
    handle_replace_symbol_body,
    handle_rename_symbol,
)

from atria.core.context_engineering.tools.registry_mixins import (
    InlineToolsMixin,
    OrchestrationOpsMixin,
    SubagentOpsMixin,
)
from atria.core.context_engineering.tools.registry_mixins.llm_wiring import _wire_llm_into_ctx


class ToolRegistry(SubagentOpsMixin, OrchestrationOpsMixin, InlineToolsMixin):
    """Dispatches tool invocations to dedicated handlers."""

    def __init__(
        self,
        file_ops: Union[Any, None] = None,
        write_tool: Union[Any, None] = None,
        edit_tool: Union[Any, None] = None,
        bash_tool: Union[Any, None] = None,
        web_fetch_tool: Union[Any, None] = None,
        web_search_tool: Union[Any, None] = None,
        notebook_edit_tool: Union[Any, None] = None,
        ask_user_tool: Union[Any, None] = None,
        open_browser_tool: Union[Any, None] = None,
        vlm_tool: Union[Any, None] = None,
        web_screenshot_tool: Union[Any, None] = None,
        mcp_manager: Union[Any, None] = None,
        app_config: Union[Any, None] = None,
    ) -> None:
        self.file_ops = file_ops
        self._app_config = app_config  # for per-run parallel orchestrator wiring
        self.write_tool = write_tool
        self.edit_tool = edit_tool
        self.bash_tool = bash_tool
        self.web_fetch_tool = web_fetch_tool
        self.web_search_tool = web_search_tool
        self.notebook_edit_tool = notebook_edit_tool
        self.ask_user_tool = ask_user_tool
        self.open_browser_tool = open_browser_tool
        self.vlm_tool = vlm_tool
        self.web_screenshot_tool = web_screenshot_tool

        self._file_handler = FileToolHandler(file_ops, write_tool, edit_tool)
        self._process_handler = ProcessToolHandler(bash_tool)
        self._web_handler = WebToolHandler(web_fetch_tool)
        self._web_search_handler = WebSearchHandler(web_search_tool)
        _skill_working_dir = (
            str(file_ops.working_dir)
            if file_ops and hasattr(file_ops, "working_dir") and file_ops.working_dir
            else None
        )
        self.skill_ctx = SkillToolContext(
            working_dir=_skill_working_dir,
            web_search=web_search_tool,
        )
        _wire_llm_into_ctx(self.skill_ctx, app_config)
        _paths = get_paths()
        _skill_dirs = [
            Path.cwd() / ".atria" / "skills",
            _paths.global_skills_dir,
        ]
        self._skill_specs: dict[str, ToolSpec] = {
            spec.name: spec
            for spec in SkillToolLoader(_skill_dirs).discover_and_register(self.skill_ctx)
        }
        self._md_to_pdf_tool = MdToPdfTool()
        self._md_to_pdf_handler_new = MdToPdfHandler(self._md_to_pdf_tool)
        self._notebook_edit_handler = NotebookEditHandler(notebook_edit_tool)
        self._ask_user_handler = AskUserHandler(ask_user_tool)
        self._mcp_handler = McpToolHandler(mcp_manager)
        self._screenshot_handler = ScreenshotToolHandler()
        self.todo_handler = TodoHandler()
        self.thinking_handler = ThinkingHandler()
        self._pdf_tool = PDFTool()
        self._agents_tool = AgentsTool()
        self._patch_tool = PatchTool()
        self._task_complete_tool = TaskCompleteTool()
        self._present_plan_tool = PresentPlanTool()
        self._subagent_manager: Union[Any, None] = None
        self._parallel_orchestrator: Union[Any, None] = None  # built lazily per run
        self._hook_manager: Union["HookManager", None] = None
        self._skill_loader: Union["SkillLoader", None] = None

        # FileTime stale-read detection (shared across the session)
        from atria.core.context_engineering.tools.file_time import FileTimeTracker

        self._file_time_tracker = FileTimeTracker()
        self._invoked_skills: set[str] = set()  # Track skills already loaded in this session

        # Token-efficient MCP tool discovery
        # Only tools in this set will have their schemas included in LLM context
        self._discovered_mcp_tools: set[str] = set()
        self._search_tools_handler = SearchToolsHandler(
            mcp_manager=mcp_manager,
            on_discover=self.discover_mcp_tool,
        )
        self._browser_handler = BrowserToolHandler()
        self._schedule_handler = ScheduleToolHandler()
        self._message_handler = MessageToolHandler()
        self._send_image_handler = SendImageHandler()
        self._render_component_handler = RenderComponentHandler()
        self._markdown_to_pdf_handler = MarkdownToPdfHandler()
        self._memory_handler = MemoryToolHandler()
        self._session_handler = SessionToolHandler()
        self._artifacts_handler = ArtifactsToolHandler()
        self._batch_handler: Union[BatchToolHandler, None] = None  # Lazy init after registry ready

        self.set_mcp_manager(mcp_manager)

        self._handlers: dict[str, Any] = {
            "write_file": self._file_handler.write_file,
            "edit_file": self._file_handler.edit_file,
            "read_file": self._file_handler.read_file,
            "list_files": self._file_handler.list_files,
            "search": self._file_handler.search,  # Unified: type="text" (default) or "ast"
            "run_command": self._process_handler.run_command,
            "list_processes": lambda args, ctx: self._process_handler.list_processes(),
            "get_process_output": self._process_handler.get_process_output,
            "kill_process": self._process_handler.kill_process,
            "fetch_url": self._web_handler.fetch_url,
            "web_search": self._web_search_handler.search,
            "md_to_pdf": self._md_to_pdf_handler_new.md_to_pdf,
            "notebook_edit": self._notebook_edit_handler.edit_cell,
            "ask_user": self._ask_user_handler.ask_questions,
            "open_browser": self._open_browser,
            "capture_screenshot": self._screenshot_handler.capture_screenshot,
            "analyze_image": self._analyze_image,
            "capture_web_screenshot": self._capture_web_screenshot,
            "write_todos": self._write_todos,
            "update_todo": self._update_todo,
            "complete_todo": self._complete_todo,
            "list_todos": lambda args, ctx=None: self.todo_handler.list_todos(),
            "clear_todos": self._clear_todos,
            # Symbol tools (LSP-based)
            "find_symbol": lambda args: handle_find_symbol(args),
            "find_referencing_symbols": lambda args: handle_find_referencing_symbols(args),
            "insert_before_symbol": lambda args: handle_insert_before_symbol(args),
            "insert_after_symbol": lambda args: handle_insert_after_symbol(args),
            "replace_symbol_body": lambda args: handle_replace_symbol_body(args),
            "rename_symbol": lambda args: handle_rename_symbol(args),
            # Subagent spawning tool
            "spawn_subagent": self._execute_spawn_subagent,
            # Get output from background subagent
            "get_subagent_output": self._get_subagent_output,
            # Unified solver tools (divide + parallel behind a strategy param)
            "solve": self._execute_solve,
            "get_solve_result": self._execute_get_solve_result,
            # PDF extraction tool
            "read_pdf": self._read_pdf,
            # MCP tool discovery (token-efficient)
            "search_tools": self._search_tools_handler.search_tools,
            # Task completion tool
            "task_complete": self._execute_task_complete,
            # Plan presentation tool
            "present_plan": self._execute_present_plan,
            # Skills system tool
            "invoke_skill": self._handle_invoke_skill,
            # Browser automation
            "browser": self._browser_handler.handle,
            # Schedule tool
            "schedule": self._schedule_handler.handle,
            # Message tool
            "send_message": self._message_handler.handle,
            # Image push tool (web UI)
            "send_image": self._send_image_handler.send,
            # Module block render tool (web UI)
            "render_component": self._render_component_handler.render,
            "markdown_to_pdf": self._markdown_to_pdf_handler.convert,
            # Memory tools
            "memory_search": self._memory_handler.search,
            "memory_write": self._memory_handler.write,
            # Session inspection tools
            "list_sessions": self._session_handler.list_sessions,
            "get_session_history": self._session_handler.get_session_history,
            "list_subagents": self._session_handler.list_subagents,
            # Batch tool for parallel/serial multi-tool execution
            "batch_tool": self._execute_batch_tool,
            # Agents listing
            "list_agents": self._handle_list_agents,
            # Apply patch
            "apply_patch": self._handle_apply_patch,
            # Artifact tools
            "list_artifact_images": self._artifacts_handler.list_artifact_images,
            "read_artifact_image": self._artifacts_handler.read_artifact_image,
            # Blackboard note tool
            "NOTE": lambda args, ctx=None: execute_note(
                args, blackboard=getattr(ctx, "blackboard", None)
            ),
        }

        # Merge skill-owned tool handlers. Each skill's tools.py returned a
        # ToolSpec; wrap its handler to match the (arguments, context) -> dict
        # calling convention used by execute_tool.
        for _name, _spec in self._skill_specs.items():
            self._handlers[_name] = self._make_skill_handler(_spec)

        # Initialize batch handler now that _handlers is set up
        self._batch_handler = BatchToolHandler(self)

    @staticmethod
    def _make_skill_handler(spec: ToolSpec):
        """Wrap a skill ToolSpec.handler into the registry's calling convention.

        Skill handlers accept **kwargs; the registry passes (arguments, context)
        or just (arguments). Either way, we forward arguments as kwargs.
        """
        handler = spec.handler

        def _call(arguments, context=None):
            try:
                return handler(**(arguments or {}))
            except TypeError:
                return handler(arguments, context)

        return _call

    def get_skill_specs(self) -> dict[str, ToolSpec]:
        """Return all skill-provided ToolSpecs by name."""
        return dict(self._skill_specs)

    def set_subagent_manager(self, manager: Any) -> None:
        """Set the subagent manager for task tool execution.

        Args:
            manager: SubAgentManager instance
        """
        self._subagent_manager = manager
        self._session_handler.set_subagent_manager(manager)

    def get_subagent_manager(self) -> Union[Any, None]:
        """Get the subagent manager.

        Returns:
            SubAgentManager instance or None
        """
        return self._subagent_manager

    def set_hook_manager(self, manager: "HookManager") -> None:
        """Set the hook manager for lifecycle hooks.

        Args:
            manager: HookManager instance
        """
        self._hook_manager = manager

    def set_skill_loader(self, loader: "SkillLoader") -> None:
        """Set the skill loader for invoke_skill tool.

        Args:
            loader: SkillLoader instance
        """
        self._skill_loader = loader

    def get_skill_loader(self) -> Union["SkillLoader", None]:
        """Get the skill loader.

        Returns:
            SkillLoader instance or None
        """
        return self._skill_loader

    # ===== Token-Efficient MCP Tool Discovery =====

    def discover_mcp_tool(self, tool_name: str) -> None:
        """Mark an MCP tool as discovered.

        Discovered tools will have their schemas included in subsequent LLM calls.
        This enables token-efficient tool loading - only tools the agent has
        explicitly searched for (or attempted to use) will consume context tokens.

        Args:
            tool_name: Full MCP tool name (e.g., 'mcp__github__create_issue')
        """
        if tool_name and tool_name.startswith("mcp__"):
            self._discovered_mcp_tools.add(tool_name)
            logger.debug(f"Discovered MCP tool: {tool_name}")

    def get_discovered_mcp_tools(self) -> list[dict[str, Any]]:
        """Get schemas only for discovered MCP tools.

        Returns:
            List of tool schema dicts for discovered tools only
        """
        if not self.mcp_manager:
            return []

        all_tools = self.mcp_manager.get_all_tools()
        return [t for t in all_tools if t.get("name") in self._discovered_mcp_tools]

    def clear_discovered_tools(self) -> None:
        """Clear all discovered MCP tools.

        Useful when starting a new conversation or resetting state.
        """
        self._discovered_mcp_tools.clear()
        logger.debug("Cleared all discovered MCP tools")

    def get_schemas(self) -> list[dict[str, Any]]:
        """Compatibility hook (schemas generated elsewhere)."""
        return []

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        mode_manager: Union[Any, None] = None,
        approval_manager: Union[Any, None] = None,
        undo_manager: Union[Any, None] = None,
        task_monitor: Union[Any, None] = None,
        session_manager: Union[Any, None] = None,
        ui_callback: Union[Any, None] = None,
        is_subagent: bool = False,
        tool_call_id: Union[str, None] = None,
        blackboard: Union[Any, None] = None,
        divide_orchestrator: Union[Any, None] = None,
        parallel_orchestrator: Union[Any, None] = None,
    ) -> dict[str, Any]:
        """Execute a tool by delegating to registered handlers."""
        if tool_name.startswith("mcp__"):
            # Auto-discover MCP tools when they're called directly
            # This ensures the tool schema will be available in future LLM calls
            if tool_name not in self._discovered_mcp_tools:
                self.discover_mcp_tool(tool_name)
                logger.info(
                    f"Auto-discovered MCP tool: {tool_name}. "
                    "Tip: Use search_tools() to discover tools before using them."
                )
            return self._mcp_handler.execute(tool_name, arguments, task_monitor=task_monitor)

        if tool_name not in self._handlers:
            return {"success": False, "error": f"Unknown tool: {tool_name}", "output": None}

        # --- PreToolUse hook ---
        if self._hook_manager:
            from atria.core.hooks.models import HookEvent

            if self._hook_manager.has_hooks_for(HookEvent.PRE_TOOL_USE):
                outcome = self._hook_manager.run_hooks(
                    HookEvent.PRE_TOOL_USE,
                    match_value=tool_name,
                    event_data={"tool_input": arguments},
                )
                if outcome.blocked:
                    return {
                        "success": False,
                        "error": f"Blocked by hook: {outcome.block_reason}",
                        "output": None,
                        "denied": True,
                    }
                if outcome.updated_input and isinstance(outcome.updated_input, dict):
                    arguments = {**arguments, **outcome.updated_input}

        # --- Parameter normalization ---
        from atria.core.context_engineering.tools.param_normalizer import normalize_params

        working_dir = None
        if hasattr(self, "file_ops") and self.file_ops and hasattr(self.file_ops, "working_dir"):
            working_dir = str(self.file_ops.working_dir) if self.file_ops.working_dir else None
        arguments = normalize_params(tool_name, arguments, working_dir)

        context = ToolExecutionContext(
            mode_manager=mode_manager,
            approval_manager=approval_manager,
            undo_manager=undo_manager,
            task_monitor=task_monitor,
            session_manager=session_manager,
            ui_callback=ui_callback,
            is_subagent=is_subagent,
            file_time_tracker=self._file_time_tracker,
            blackboard=blackboard,
            divide_orchestrator=divide_orchestrator,
            parallel_orchestrator=parallel_orchestrator,
        )

        handler = self._handlers[tool_name]
        try:
            if tool_name == "spawn_subagent":
                # spawn_subagent needs tool_call_id for parent context tracking
                result = self._execute_spawn_subagent(arguments, context, tool_call_id)
            elif tool_name in {
                "write_file",
                "edit_file",
                "read_file",
                "run_command",
                "batch_tool",
                "present_plan",
                "list_sessions",
                "get_session_history",
                "send_image",
                "list_artifact_images",
                "read_artifact_image",
                "NOTE",
                "solve",
                "get_solve_result",
                "write_todos",
                "update_todo",
                "complete_todo",
                "clear_todos",
            }:
                # Handlers requiring context
                result = handler(arguments, context)
            elif tool_name == "list_processes":
                result = handler(arguments, context)
            elif tool_name in {"get_process_output", "kill_process"}:
                result = handler(arguments)
            else:
                # Remaining handlers ignore execution context
                result = handler(arguments)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, InterruptedError):
                raise
            import traceback as _tb

            logger.error("Tool execution failed: %s\n%s", exc, _tb.format_exc())
            result = {"success": False, "error": str(exc), "output": None}

        # --- PostToolUse / PostToolUseFailure hook ---
        if self._hook_manager:
            from atria.core.hooks.models import HookEvent

            is_success = result.get("success", False)
            post_event = HookEvent.POST_TOOL_USE if is_success else HookEvent.POST_TOOL_USE_FAILURE
            if self._hook_manager.has_hooks_for(post_event):
                self._hook_manager.run_hooks_async(
                    post_event,
                    match_value=tool_name,
                    event_data={
                        "tool_input": arguments,
                        "tool_response": result,
                    },
                )

        return result

    def set_mcp_manager(self, mcp_manager: Union[Any, None]) -> None:
        """Update the MCP manager and refresh the handlers."""
        self.mcp_manager = mcp_manager
        self._mcp_handler = McpToolHandler(mcp_manager)
        self._search_tools_handler.set_mcp_manager(mcp_manager)
