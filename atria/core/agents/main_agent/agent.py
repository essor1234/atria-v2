"""Main agent class composing HTTP, LLM, and run loop mixins."""

from __future__ import annotations

import queue as queue_mod
from typing import Any

from atria.core.base.abstract import BaseAgent
from atria.core.agents.components import (
    ResponseCleaner,
    SystemPromptBuilder,
    ThinkingPromptBuilder,
    ToolSchemaBuilder,
)
from atria.core.agents.prompts import get_reminder
from atria.models.config import AppConfig
from atria.core.agents.main_agent.http_clients import HttpClientMixin
from atria.core.agents.main_agent.llm_calls import LlmCallsMixin
from atria.core.agents.main_agent.run_loop import RunLoopMixin
from atria.core.agents.prompts.loader import load_tool_description_from_path


def _build_skill_schemas(tool_registry: object) -> list[dict]:
    """Build OpenAI tool schemas from the registry's skill-owned ToolSpecs."""
    get_specs = getattr(tool_registry, "get_skill_specs", None)
    if get_specs is None:
        return []
    schemas: list[dict] = []
    for spec in get_specs().values():
        description = spec.description
        if spec.card_path is not None and spec.card_path.exists():
            try:
                description = load_tool_description_from_path(spec.card_path)
            except OSError:
                pass
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": description,
                    "parameters": spec.parameters,
                },
            }
        )
    return schemas


class WebInterruptMonitor:
    """Monitor for checking web interrupt requests."""

    def __init__(self, web_state: Any):
        self.web_state = web_state

    def should_interrupt(self) -> bool:
        """Check if interrupt has been requested."""
        return self.web_state.is_interrupt_requested()


class MainAgent(HttpClientMixin, LlmCallsMixin, RunLoopMixin, BaseAgent):
    """Custom agent that coordinates LLM interactions via HTTP."""

    @staticmethod
    def _classify_error(error_text: str) -> str:
        """Classify error type for targeted nudge selection.

        Args:
            error_text: The error message from a failed tool execution

        Returns:
            Error classification string matching a nudge_* reminder name suffix
        """
        error_lower = error_text.lower()
        if "permission denied" in error_lower:
            return "permission_error"
        if "old_content" in error_lower or "old content" in error_lower:
            return "edit_mismatch"
        if "no such file" in error_lower or "not found" in error_lower:
            return "file_not_found"
        if "syntax" in error_lower:
            return "syntax_error"
        if "429" in error_lower or "rate limit" in error_lower:
            return "rate_limit"
        if "timeout" in error_lower or "timed out" in error_lower:
            return "timeout"
        return "generic"

    def _get_smart_nudge(self, error_text: str) -> str:
        """Get a failure-type-specific nudge message.

        Args:
            error_text: The error message from a failed tool execution

        Returns:
            Appropriate nudge message for the error type
        """
        error_type = self._classify_error(error_text)
        if error_type == "generic":
            return get_reminder("failed_tool_nudge")
        try:
            return get_reminder(f"nudge_{error_type}")
        except KeyError:
            return get_reminder("failed_tool_nudge")

    def _check_todo_completion(self) -> tuple[bool, str]:
        """Check if completion is allowed given todo state.

        This validation ensures todos are properly completed before the agent
        finishes. It covers all completion paths: implicit, exhausted nudges,
        and explicit task_complete.

        Returns:
            Tuple of (can_complete, nudge_message):
            - can_complete: True if OK to complete, False if incomplete todos exist
            - nudge_message: Message prompting agent to complete todos (empty if can_complete)
        """
        if not hasattr(self, "tool_registry") or not self.tool_registry:
            return True, ""

        todo_handler = getattr(self.tool_registry, "todo_handler", None)
        if not todo_handler:
            return True, ""

        if not todo_handler.has_todos():
            return True, ""  # No todos created - OK to complete

        incomplete = todo_handler.get_incomplete_todos()
        if not incomplete:
            return True, ""  # All todos done - OK to complete

        # Build nudge message with incomplete todo titles
        titles = [t.title for t in incomplete[:3]]
        todo_list = "\n".join(f"  \u2022 {title}" for title in titles)
        if len(incomplete) > 3:
            todo_list += "\n  ..."
        msg = get_reminder(
            "incomplete_todos_nudge",
            count=str(len(incomplete)),
            todo_list=todo_list,
        )
        return False, msg

    @staticmethod
    def _messages_contain_images(messages: list[dict]) -> bool:
        """Check if any message contains multimodal image content blocks."""
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "image":
                        return True
        return False

    def __init__(
        self,
        config: AppConfig,
        tool_registry: Any,
        mode_manager: Any,
        working_dir: Any = None,
        allowed_tools: Any = None,
        env_context: Any = None,
    ) -> None:
        """Initialize the MainAgent.

        Args:
            config: Application configuration
            tool_registry: The tool registry for tool execution
            mode_manager: Mode manager for operation mode
            working_dir: Optional working directory for file operations
            allowed_tools: Optional list of allowed tool names for filtering.
                          If None, all tools are allowed. Used by subagents
                          to restrict available tools (e.g., Code-Explorer
                          only gets read_file, search, list_files, etc.)
            env_context: Optional EnvironmentContext for rich system prompt
        """
        self._priv_http_client = None  # Lazy initialization - defer API key validation
        self._priv_thinking_http_client = None  # Lazy initialization for Thinking model
        self._priv_critique_http_client = None  # Lazy initialization for Critique model
        self._priv_vlm_http_client = None  # Lazy initialization for VLM model
        self._compactor = None  # Lazy initialization for context compaction
        self._response_cleaner = ResponseCleaner()
        self._working_dir = working_dir
        self._env_context = env_context
        _bb_enabled = getattr(getattr(config, "blackboard", None), "enabled", False)
        self._schema_builder = ToolSchemaBuilder(
            tool_registry,
            allowed_tools,
            extra_schemas=_build_skill_schemas(tool_registry),
            blackboard_enabled=_bb_enabled,
        )
        self.is_subagent = allowed_tools is not None

        # Live message injection queue (thread-safe, bounded)
        self._injection_queue: queue_mod.Queue[str] = queue_mod.Queue(maxsize=10)

        super().__init__(config, tool_registry, mode_manager)

    def build_system_prompt(self, thinking_visible: bool = False) -> str:
        """Build the system prompt for the agent.

        Also computes the stable/dynamic split for prompt caching. The
        stable part becomes the system message content; the dynamic part
        is passed as ``_system_dynamic`` in the payload.

        Args:
            thinking_visible: If True, use thinking-specialized prompt

        Returns:
            The formatted system prompt string (stable + dynamic combined)
        """
        if thinking_visible:
            builder = ThinkingPromptBuilder(
                self.tool_registry, self._working_dir, env_context=self._env_context
            )
            full = builder.build()
            self._system_stable = full
            self._system_dynamic = ""
            return full

        builder = SystemPromptBuilder(
            self.tool_registry,
            self._working_dir,
            env_context=self._env_context,
            blackboard=getattr(self, "_blackboard_handle", None),
        )
        stable, dynamic = builder.build_two_part()
        self._system_stable = stable
        self._system_dynamic = dynamic
        # Return combined prompt for contexts that need a single string
        if dynamic:
            return f"{stable}\n\n{dynamic}"
        return stable

    def build_tool_schemas(self, thinking_visible: bool = True) -> list[dict[str, Any]]:
        return self._schema_builder.build(thinking_visible=thinking_visible)

    def _maybe_compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Auto-compact messages if approaching the context window limit."""
        if self._compactor is None:
            from atria.core.context_engineering.compaction import ContextCompactor

            self._compactor = ContextCompactor(self.config, self._http_client)

        if self._compactor.should_compact(messages, self.system_prompt):
            return self._compactor.compact_with_retry(messages, self.system_prompt)
        return messages
