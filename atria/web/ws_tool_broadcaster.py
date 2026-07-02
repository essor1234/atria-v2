"""WebSocket broadcaster for tool execution events."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from atria.core.paths import atria_dir
from atria.web.logging_config import logger
from atria.web.protocol import WSMessageType
from atria.core.utils.tool_result_summarizer import summarize_tool_result
from atria.core.utils.tool_display import (
    PATH_ARG_KEYS as _PATH_KEYS,
    format_tool_call,
)


class WebSocketToolBroadcaster:
    """Wraps tool registry to broadcast tool execution events via WebSocket."""

    _BASH_TOOLS: frozenset[str] = frozenset({"bash_execute", "run_command"})

    _SANDBOXED_TOOLS: frozenset[str] = frozenset(
        {
            "write_file",
            "edit_file",
            "read_file",
            "list_files",
            "search",
        }
    )

    # Tools that emit their own custom UI events; skip the generic
    # tool_call / tool_result broadcasts so the UI shows only the custom event.
    _SUPPRESSED_BROADCAST_TOOLS: frozenset[str] = frozenset(
        {"send_image", "send_editable_table"}
    )

    _PATH_ARGS: dict[str, str] = {
        "write_file": "file_path",
        "edit_file": "file_path",
        "read_file": "file_path",
        "list_files": "path",
        "search": "path",
    }

    def __init__(
        self,
        tool_registry: Any,
        ws_manager: Any,
        loop: asyncio.AbstractEventLoop,
        working_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
    ):
        """Initialize broadcaster.

        Args:
            tool_registry: The tool registry to wrap
            ws_manager: WebSocket manager for broadcasting
            loop: Event loop for async operations
            working_dir: Working directory for path resolution
            session_id: Session ID for scoping broadcasts
        """
        self.tool_registry = tool_registry
        self.ws_manager = ws_manager
        self.loop = loop
        self.working_dir = Path(working_dir).resolve() if working_dir else None
        self.session_id = session_id

        # Wire skill-tool broadcaster — any skill that emits typed events
        # routes through here. Each skill's tools.py decides which events
        # it emits; we fan them out by event type.
        skill_ctx = getattr(tool_registry, "skill_ctx", None)
        if skill_ctx is not None:
            skill_ctx.broadcaster = self._broadcast_skill_event

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Execute tool with WebSocket broadcasting.

        Broadcasts tool_call before execution and tool_result after.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            **kwargs: Additional execution context

        Returns:
            Tool execution result
        """
        call_id = uuid.uuid4().hex
        arguments = arguments or {}
        normalized_args = self._normalize_arguments(arguments) or {}
        display = format_tool_call(tool_name, normalized_args)

        suppress_broadcast = tool_name in self._SUPPRESSED_BROADCAST_TOOLS

        sandbox_err = self._sandbox_check(tool_name, arguments)
        if sandbox_err:
            if not suppress_broadcast:
                self._broadcast_tool_call(call_id, tool_name, normalized_args, display)
            deny_result = {"success": False, "error": sandbox_err, "output": sandbox_err}
            if not suppress_broadcast:
                payload = self._build_result_payload(
                    call_id, tool_name, deny_result, normalized_args
                )
                self._broadcast_tool_result(payload)
            return deny_result

        if not suppress_broadcast:
            self._broadcast_tool_call(call_id, tool_name, normalized_args, display)

        result = self.tool_registry.execute_tool(tool_name, arguments, **kwargs)

        if not suppress_broadcast:
            payload = self._build_result_payload(call_id, tool_name, result, normalized_args)
            self._broadcast_tool_result(payload)

        if tool_name == "web_search" and isinstance(result, dict) and result.get("success"):
            self._broadcast_search_done(result)

        return result

    def _broadcast_tool_call(
        self,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        display: str | None,
    ) -> None:
        """Broadcast tool call event."""
        try:
            payload = self._make_json_safe(
                {
                    "type": WSMessageType.TOOL_CALL,
                    "data": {
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "arguments_display": display,
                        "description": f"Calling {tool_name}",
                        "activity": self._activity_for(tool_name, arguments),
                        "session_id": self.session_id,
                    },
                }
            )
            future = asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(payload),
                self.loop,
            )
            future.result(timeout=2)
            logger.info(f"✓ Broadcasted tool_call: {tool_name}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"❌ Failed to broadcast tool call: {e}")
            logger.error(f"Tool: {tool_name}, Args: {arguments}")

    def _broadcast_skill_event(self, event: Dict[str, Any]) -> None:
        """Broadcast a skill-emitted event over the WS as-is."""
        etype = event.get("type", "")
        try:
            payload = self._make_json_safe(
                {
                    "type": etype or "skill_event",
                    "data": {**event, "session_id": self.session_id},
                }
            )
            future = asyncio.run_coroutine_threadsafe(self.ws_manager.broadcast(payload), self.loop)
            future.result(timeout=5)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to broadcast skill event: {e}")

    def _broadcast_search_done(self, result: Dict[str, Any]) -> None:
        """Broadcast search_done event with query and result list."""
        try:
            raw_results = result.get("results") or []
            results_payload = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "domain": r.get("domain", ""),
                }
                for r in raw_results
            ]
            payload = {
                "type": WSMessageType.SEARCH_DONE,
                "data": {
                    "query": result.get("query", ""),
                    "result_count": result.get("result_count", len(raw_results)),
                    "results": results_payload,
                    "provider": result.get("provider", ""),
                    "session_id": self.session_id,
                },
            }
            future = asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(payload),
                self.loop,
            )
            future.result(timeout=2)
        except Exception as e:  # noqa: BLE001
            logger.error(f"❌ Failed to broadcast search_done: {e}")

    def _broadcast_tool_result(self, payload: Dict[str, Any]) -> None:
        """Broadcast tool result event."""
        try:
            safe_payload = self._make_json_safe(
                {
                    "type": WSMessageType.TOOL_RESULT,
                    "data": {**payload, "session_id": self.session_id},
                }
            )
            future = asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(safe_payload),
                self.loop,
            )
            future.result(timeout=2)
            logger.info(f"✓ Broadcasted tool_result: {payload.get('tool_name')}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"❌ Failed to broadcast tool result: {e}")
            logger.error(f"Payload: {payload.get('tool_name')}")

    def _build_result_payload(
        self,
        call_id: str,
        tool_name: str,
        result: Dict[str, Any],
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a JSON-serializable payload mirroring terminal summaries."""
        success = bool(result.get("success"))
        output_text = self._stringify_output(result)
        summary = summarize_tool_result(tool_name, output_text, result.get("error"))
        argument_summary = format_tool_call(tool_name, arguments or {})

        return {
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "success": success,
            "summary": summary,
            "arguments": arguments,
            "arguments_display": argument_summary,
            "error": result.get("error"),
            "output": output_text,
            "raw_result": self._make_json_safe(result),
            "activity": self._activity_for(tool_name, arguments),
        }

    def _activity_for(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Friendly running/done labels for a module-script bash call, else None."""
        if tool_name not in self._BASH_TOOLS:
            return None
        command = arguments.get("command") if isinstance(arguments, dict) else None
        if not command:
            return None
        try:
            from atria.core.modules.activity import resolve_activity_label
            from atria.core.modules.registry import resolve_modules_root

            label = resolve_activity_label(str(command), resolve_modules_root())
        except Exception:  # noqa: BLE001 — labelling must never break broadcasting
            return None
        if label is None:
            return None
        return {"running": label.running, "done": label.done}

    def _sandbox_check(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Return error string if path falls outside working_dir; else None."""
        if not self.working_dir or tool_name not in self._SANDBOXED_TOOLS:
            return None
        path_key = self._PATH_ARGS.get(tool_name)
        if not path_key:
            return None
        raw_path = arguments.get(path_key)
        if not raw_path:
            return None
        from atria.core.workspace.manager import is_within_workspace

        # Resolve relative paths against working_dir (the conversation
        # workspace) to match how the file tools resolve them — otherwise a
        # relative path like '.' or 'note.csv' resolves against the backend's
        # process CWD and is wrongly rejected as outside the workspace.
        # Fully resolve so '..' escapes can't slip past the boundary check.
        resolved = Path(str(raw_path)).expanduser()
        if not resolved.is_absolute():
            resolved = self.working_dir / resolved
        resolved = resolved.resolve()
        # Always allow reads/writes inside the atria scratch/data directory
        atria_home = atria_dir()
        if resolved.is_absolute() and str(resolved).startswith(str(atria_home)):
            return None
        # Always allow reads/writes inside the active modules root — modules are
        # source-tracked skills the agent legitimately needs to invoke regardless
        # of the active session workspace.
        try:
            from atria.core.modules.registry import resolve_modules_root

            modules_root = str(resolve_modules_root())
            if resolved.is_absolute() and str(resolved).startswith(modules_root):
                return None
        except Exception:  # noqa: BLE001 — guard must not fail open on unrelated errors
            pass
        if not is_within_workspace(resolved, self.working_dir):
            return (
                f"Access denied: '{raw_path}' is outside the project workspace "
                f"({self.working_dir}). The agent may only read/write files within "
                f"the current conversation folder."
            )
        return None

    def _normalize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._make_json_safe(arguments)
        if not isinstance(normalized, dict):
            return normalized
        return {
            key: self._normalize_argument_value(key, value) for key, value in normalized.items()
        }

    def _normalize_argument_value(self, key: str, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                sub_key: self._normalize_argument_value(sub_key, sub_value)
                for sub_key, sub_value in value.items()
            }
        if isinstance(value, list):
            return [self._normalize_argument_value(key, item) for item in value]
        if isinstance(value, str) and key in _PATH_KEYS:
            return self._resolve_path(value)
        return value

    def _resolve_path(self, value: str) -> str:
        raw_path = Path(value.strip())
        if raw_path.is_absolute():
            return str(raw_path)
        if self.working_dir:
            return str((self.working_dir / raw_path).resolve())
        try:
            return str(raw_path.resolve())
        except Exception:  # noqa: BLE001
            return str(raw_path)

    def _stringify_output(self, result: Dict[str, Any]) -> str:
        """Do best-effort string conversion for tool output."""
        output = result.get("output")
        if isinstance(output, str):
            return output
        if output is None and "matches" in result:
            matches = result.get("matches") or []
            return "\n".join(str(match) for match in matches)
        if output is None and "entries" in result:
            entries = result.get("entries") or []
            return "\n".join(str(entry) for entry in entries)
        if output is None:
            return ""

        try:
            return json.dumps(self._make_json_safe(output))
        except TypeError:
            return str(output)

    def _make_json_safe(self, value: Any) -> Any:
        """Recursively convert values to JSON-safe representations."""
        # Handle None and primitives first
        if value is None or isinstance(value, (bool, int, float, str)):
            return value

        # Handle collections
        if isinstance(value, dict):
            try:
                return {str(key): self._make_json_safe(val) for key, val in value.items()}
            except Exception:  # noqa: BLE001
                return str(value)

        if isinstance(value, (list, tuple)):
            try:
                return [self._make_json_safe(item) for item in value]
            except Exception:  # noqa: BLE001
                return str(value)

        if isinstance(value, set):
            try:
                return [self._make_json_safe(item) for item in value]
            except Exception:  # noqa: BLE001
                return str(value)

        # Handle special types
        if isinstance(value, Path):
            return str(value)

        if isinstance(value, datetime):
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                return str(value)

        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                return ""

        # Handle objects with __dict__
        if hasattr(value, "__dict__"):
            try:
                return self._make_json_safe(value.__dict__)
            except Exception:  # noqa: BLE001
                return str(value)

        # Final fallback
        try:
            return str(value)
        except Exception:  # noqa: BLE001
            return "<unserializable>"

    def set_subagent_manager(self, manager: Any) -> None:
        """Set the subagent manager, delegating to the underlying registry.

        This preserves the subagent manager reference when the tool registry
        is wrapped with the WebSocket broadcaster.

        Args:
            manager: SubAgentManager instance
        """
        if hasattr(self.tool_registry, "set_subagent_manager"):
            self.tool_registry.set_subagent_manager(manager)

    @property
    def _subagent_manager(self) -> Any:
        """Get subagent manager from the underlying registry."""
        return getattr(self.tool_registry, "_subagent_manager", None)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the wrapped tool registry."""
        return getattr(self.tool_registry, name)
