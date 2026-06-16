"""Agent executor for WebSocket queries with streaming support."""

from __future__ import annotations

import atexit
import asyncio
import functools
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Tuple

from atria.web.state import WebState
from atria.web.logging_config import logger
from atria.web.protocol import WSMessageType
from atria.core.runtime import ConfigManager
from atria.models.config import AppConfig


class AgentExecutor:
    """Executes agent queries in background with WebSocket streaming."""

    def __init__(self, state: WebState):
        """Initialize agent executor.

        Args:
            state: Shared web state
        """
        self.state = state
        self.executor = ThreadPoolExecutor(max_workers=4)
        # Lock protecting session_manager.current_session mutation
        self._session_lock = __import__("threading").Lock()
        atexit.register(self.executor.shutdown, wait=False)

        # Shared thread pool for parallel tool execution across sessions
        self._shared_parallel_executor = ThreadPoolExecutor(
            max_workers=5, thread_name_prefix="web-tool"
        )
        atexit.register(self._shared_parallel_executor.shutdown, wait=False)

        # Current ReactExecutor per session (for interrupt bridging)
        self._current_react_executors: Dict[str, Any] = {}

    def interrupt_session(self, session_id: str) -> bool:
        """Interrupt a running session's ReactExecutor.

        Args:
            session_id: Session ID to interrupt

        Returns:
            True if interrupt was requested, False if no executor found
        """
        executor = self._current_react_executors.get(session_id)
        if executor:
            return executor.request_interrupt()
        return False

    async def execute_query(
        self,
        message: str,
        ws_manager: Any,
        *,
        session_id: str,
        session: Any,
        persona_name: str | None = None,
    ) -> None:
        """Execute query and stream results via WebSocket.

        Args:
            message: User query
            ws_manager: WebSocket manager for broadcasting
            session_id: Session ID for scoping this execution
            session: Pre-loaded Session object (avoids mutating current_session)
            persona_name: Optional persona name to prepend its system prompt
        """
        try:
            # Mark session as running
            self.state.set_session_running(session_id)
            await ws_manager.broadcast(
                {
                    "type": WSMessageType.SESSION_ACTIVITY,
                    "data": {"session_id": session_id, "status": "running"},
                }
            )

            # Broadcast message start
            try:
                await ws_manager.broadcast(
                    {
                        "type": WSMessageType.MESSAGE_START,
                        "data": {
                            "messageId": str(time.time()),
                            "session_id": session_id,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Failed to broadcast message_start: {e}")

            # Run agent in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                functools.partial(
                    self._run_agent_sync,
                    message,
                    ws_manager,
                    loop,
                    session_id,
                    session,
                    persona_name=persona_name,
                ),
            )

            # ReactExecutor handles step-by-step persistence — just log the result
            logger.info(
                f"Agent response: summary={(response.get('summary') or '')[:100]}, "
                f"error={response.get('error')}"
            )

            # Broadcast message complete
            try:
                await ws_manager.broadcast(
                    {
                        "type": WSMessageType.MESSAGE_COMPLETE,
                        "data": {
                            "messageId": str(time.time()),
                            "session_id": session_id,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Failed to broadcast message_complete: {e}")

        except Exception as e:
            # Broadcast structured error
            logger.error(f"Agent execution error: {e}")
            import traceback

            logger.error(traceback.format_exc())
            try:
                from atria.core.errors import StructuredError, classify_api_error

                if isinstance(e, StructuredError):
                    structured = e
                else:
                    structured = classify_api_error(str(e))
                await ws_manager.broadcast(
                    {
                        "type": WSMessageType.ERROR,
                        "data": {
                            "message": structured.message,
                            "category": structured.category.value,
                            "is_retryable": structured.is_retryable,
                            "status_code": structured.status_code,
                            "session_id": session_id,
                        },
                    }
                )
            except Exception as broadcast_err:
                logger.error(f"Failed to broadcast error: {broadcast_err}")
        finally:
            # Clean up ReactExecutor reference
            self._current_react_executors.pop(session_id, None)
            # Clear the ui_bridge registries so push_block calls after the run
            # raise instead of broadcasting to a torn-down session.
            try:
                from atria.web.ui_bridge import (
                    clear_runtime_context,
                    clear_session_ui_callback,
                    set_current_ui_callback,
                )

                clear_session_ui_callback(session_id)
                set_current_ui_callback(None)
                clear_runtime_context(session_id)
            except Exception as _e:
                logger.warning(f"Failed to clear ui_bridge callback: {_e}")
            # Always mark session as idle and clean up injection queue + approvals
            self.state.set_session_idle(session_id)
            self.state.clear_injection_queue(session_id)
            self.state.clear_session_approvals(session_id)
            try:
                await ws_manager.broadcast(
                    {
                        "type": WSMessageType.SESSION_ACTIVITY,
                        "data": {"session_id": session_id, "status": "idle"},
                    }
                )
            except Exception:
                pass

    def _run_agent_sync(
        self,
        message: str,
        ws_manager: Any,
        loop: asyncio.AbstractEventLoop,
        session_id: str,
        session: Any,
        *,
        persona_name: str | None = None,
    ) -> Dict[str, Any]:
        """Run agent synchronously in thread pool using ReactExecutor.

        Args:
            message: User query
            ws_manager: WebSocket manager
            loop: Event loop for async operations
            session_id: Session ID for scoping
            session: Pre-loaded Session object
            persona_name: Optional persona name to prepend its system prompt

        Returns:
            Dict with summary, error, latency_ms
        """
        from atria.core.runtime.services import RuntimeService
        from atria.core.context_engineering.tools.implementations import (
            FileOperations,
            WriteTool,
            EditTool,
            BashTool,
            WebFetchTool,
            OpenBrowserTool,
            WebScreenshotTool,
        )
        from atria.core.context_engineering.tools.implementations.web_search_tool import (
            WebSearchTool,
        )
        from atria.core.context_engineering.tools.implementations.notebook_edit_tool import (
            NotebookEditTool,
        )
        from atria.core.context_engineering.tools.implementations.ask_user_tool import AskUserTool
        from atria.web.web_approval_manager import WebApprovalManager
        from atria.web.web_ask_user_manager import WebAskUserManager
        from atria.web.web_ui_callback import WebUICallback
        from atria.web.ws_tool_broadcaster import WebSocketToolBroadcaster
        from atria.repl.react_executor import ReactExecutor

        # Clear any previous interrupt flags
        self.state.clear_interrupt()

        # Resolve config/working directory from session (no mutation of current_session)
        config_manager, config, working_dir = self._resolve_runtime_context_for_session(session)

        # Initialize tools
        file_ops = FileOperations(config, working_dir)
        write_tool = WriteTool(config, working_dir)
        edit_tool = EditTool(config, working_dir)
        bash_tool = BashTool(config, working_dir)
        web_fetch_tool = WebFetchTool(config, working_dir)
        web_search_tool = WebSearchTool(config, working_dir)
        notebook_edit_tool = NotebookEditTool(working_dir)
        # Create web-based ask-user manager with session_id
        web_ask_user_manager = WebAskUserManager(ws_manager, loop, session_id=session_id)
        ask_user_tool = AskUserTool(ui_prompt_callback=web_ask_user_manager.prompt_user)
        open_browser_tool = OpenBrowserTool(config, working_dir)
        web_screenshot_tool = WebScreenshotTool(config, working_dir)

        # Create web-based approval manager with session_id
        web_approval_manager = WebApprovalManager(ws_manager, loop, session_id=session_id)

        # Create web UI callback for plan approval, subagent events, etc.
        web_ui_callback = WebUICallback(ws_manager, loop, session_id, self.state)

        # Register the callback so module code (push_block, etc.) can reach it
        # via session_id or the contextvar. Cleared in the run-cleanup path.
        from atria.web.ui_bridge import set_current_ui_callback

        set_current_ui_callback(web_ui_callback)

        # Build runtime suite
        runtime_service = RuntimeService(config_manager, self.state.mode_manager)
        runtime_suite = runtime_service.build_suite(
            file_ops=file_ops,
            write_tool=write_tool,
            edit_tool=edit_tool,
            bash_tool=bash_tool,
            web_fetch_tool=web_fetch_tool,
            web_search_tool=web_search_tool,
            notebook_edit_tool=notebook_edit_tool,
            ask_user_tool=ask_user_tool,
            open_browser_tool=open_browser_tool,
            web_screenshot_tool=web_screenshot_tool,
            mcp_manager=self.state.mcp_manager,
        )

        # Wire hooks system (4-point wiring, matching TUI's repl.py)
        hook_manager = None
        try:
            from atria.core.hooks.loader import load_hooks_config
            from atria.core.hooks.manager import HookManager

            hooks_config = load_hooks_config(working_dir)
            if hooks_config and hooks_config.hooks:
                hook_manager = HookManager(
                    hooks_config, session_id=session_id, cwd=str(working_dir)
                )
                # 1. Tool registry
                runtime_suite.tool_registry.set_hook_manager(hook_manager)
                # 2. Subagent manager
                subagent_mgr = runtime_suite.tool_registry.get_subagent_manager()
                if subagent_mgr and hasattr(subagent_mgr, "set_hook_manager"):
                    subagent_mgr.set_hook_manager(hook_manager)
        except Exception as e:
            logger.warning(f"Failed to wire hooks: {e}")

        # Set thinking level from web state
        from atria.core.context_engineering.tools.handlers.thinking_handler import ThinkingLevel

        thinking_level_str = self.state.get_thinking_level()
        try:
            thinking_level = ThinkingLevel(thinking_level_str)
        except ValueError:
            thinking_level = ThinkingLevel.MEDIUM
        runtime_suite.tool_registry.thinking_handler.set_level(thinking_level)

        # Wrap tool registry with WebSocket broadcaster (includes session_id)
        wrapped_registry = WebSocketToolBroadcaster(
            runtime_suite.tool_registry,
            ws_manager,
            loop,
            working_dir=working_dir,
            session_id=session_id,
        )

        # Expose the live runtime suite to ui_bridge so block_rpc tool.invoke can
        # dispatch via the same wrapped registry/approval manager used by the agent.
        try:
            from atria.web.ui_bridge import set_runtime_context

            set_runtime_context(
                session_id,
                {
                    "tool_registry": wrapped_registry,
                    "approval_manager": web_approval_manager,
                    "ui_callback": web_ui_callback,
                    "working_dir": working_dir,
                    "config": config,
                },
            )
        except Exception as _ctx_err:
            logger.warning(f"Failed to register runtime context: {_ctx_err}")

        # Instantiate CostTracker for this execution
        from atria.core.runtime.cost_tracker import CostTracker

        cost_tracker = CostTracker()

        # Get agent
        agent = runtime_suite.agents.normal
        agent.tool_registry = wrapped_registry
        agent._cost_tracker = cost_tracker

        # Point session manager at the right session for this execution.
        # Protected by lock to avoid race conditions with concurrent requests.
        with self._session_lock:
            self.state.session_manager.current_session = session

        # Prepare messages for the ReAct loop
        message_history = session.to_api_messages()

        # Inject system prompt (TUI path does this via query_enhancer.prepare_messages)
        # Append working directory context so the agent knows where to write files.
        system_content = agent.system_prompt
        # Prepend persona system prompt if one was selected for this run
        if persona_name:
            from atria.core.personas.manager import PersonaManager

            persona = PersonaManager().get_persona(persona_name)
            if persona:
                system_content = persona.system_prompt + "\n\n" + system_content
            else:
                logger.warning(f"Persona '{persona_name}' not found, using base system prompt")
        wd_str = str(working_dir)
        if wd_str and wd_str not in system_content:
            system_content += (
                f"\n\n## Workspace\n\n"
                f"Your working directory for this conversation is `{wd_str}`. "
                f"All files you create or save MUST be placed inside this directory. "
                f"Use relative paths when possible."
            )

        # Inject the file-based module SKILL block into the cached prefix so the LLM
        # provider's prefix cache picks it up. Stable across turns; rebuilt only when
        # the registry version bumps (i.e. when files change on disk).
        try:
            from atria.core.modules.prompt import build_skill_block
            from atria.core.modules.registry import get_registry as _get_module_registry

            _modules_block = build_skill_block(_get_module_registry())
        except Exception as _mod_err:  # never let modules break a chat turn
            logger.warning("Failed to build module SKILL block: %s", _mod_err)
            _modules_block = ""

        if _modules_block:
            skill_block = "\n\n" + _modules_block
            system_content += skill_block
            if hasattr(agent, "_system_stable") and agent._system_stable:
                agent._system_stable += skill_block

        if not message_history or message_history[0].get("role") != "system":
            message_history.insert(0, {"role": "system", "content": system_content})
        elif message_history[0].get("role") == "system" and wd_str not in message_history[0].get(
            "content", ""
        ):
            message_history[0]["content"] += (
                f"\n\n## Workspace\n\n" f"Working directory: `{wd_str}`. Write all files here."
            )

        # Create ReactExecutor (no console, no llm_caller, no tool_executor — Web UI mode)
        react_executor = ReactExecutor(
            session_manager=self.state.session_manager,
            config=config,
            mode_manager=self.state.mode_manager,
            console=None,
            llm_caller=None,
            tool_executor=None,
            cost_tracker=cost_tracker,
            parallel_executor=self._shared_parallel_executor,
        )

        # 3. Wire hooks into react_executor (covers query_processor path)
        if hook_manager:
            react_executor.set_hook_manager(hook_manager)

        # 4. Wire hooks into compactor (matches TUI's repl.py:363-366)
        if hook_manager and hasattr(react_executor, "_compactor"):
            compactor = react_executor._compactor
            if compactor and hasattr(compactor, "set_hook_manager"):
                compactor.set_hook_manager(hook_manager)

        # Wire injection queue for mid-execution user messages
        react_executor._injection_queue = self.state.get_injection_queue(session_id)

        # Store for interrupt bridging
        self._current_react_executors[session_id] = react_executor

        # Execute unified ReAct loop
        try:
            # Fire SESSION_START hook (matches TUI's repl.py:474)
            if hook_manager:
                from atria.core.hooks.models import HookEvent

                hook_manager.run_hooks(HookEvent.SESSION_START, match_value="web_query")

            # Expand @file mentions — TUI path does this via query_enhancer.prepare_messages
            import re as _re
            from atria.repl.file_content_injector import FileContentInjector

            _injector = FileContentInjector(file_ops, config, working_dir)
            _injection = _injector.inject_content(message)
            if _injection.text_content:
                # Strip @ prefix from file references so the agent doesn't
                # construct tool paths with @ (e.g. @.artifacts/... → .artifacts/...)
                _clean_msg = _re.sub(
                    r"(?:^|(?<=\s)|(?<=[^\w]))@([a-zA-Z0-9_./\-]+)",
                    r"\1",
                    message,
                )
                query = _clean_msg + "\n\n" + _injection.text_content
            else:
                query = message

            summary, error, latency_ms = react_executor.execute(
                query=query,
                messages=message_history,
                agent=agent,
                tool_registry=wrapped_registry,
                approval_manager=web_approval_manager,
                undo_manager=self.state.undo_manager,
                ui_callback=web_ui_callback,
            )
            return {"summary": summary, "error": error, "latency_ms": latency_ms}
        except Exception as e:
            logger.error(f"ReactExecutor error: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"summary": None, "error": str(e), "latency_ms": 0}
        finally:
            # Fire SESSION_END hook (matches TUI's repl.py:690)
            if hook_manager:
                try:
                    from atria.core.hooks.models import HookEvent

                    hook_manager.run_hooks(HookEvent.SESSION_END)
                    hook_manager.shutdown()
                except Exception as e:
                    logger.warning(f"Failed to run SESSION_END hook: {e}")

    def _resolve_runtime_context_for_session(
        self, session: Any
    ) -> Tuple[ConfigManager, AppConfig, Path]:
        """Determine config manager, config, and working dir for a specific session."""
        if session and session.working_directory:
            working_dir = Path(session.working_directory).expanduser().resolve()
            config_manager = ConfigManager(working_dir)
            config = config_manager.get_config()
        else:
            config_manager = self.state.config_manager
            config = config_manager.get_config()
            working_dir = Path(config_manager.working_dir).resolve()

        try:
            config_manager.ensure_directories()
        except Exception:
            pass

        return config_manager, config, working_dir
