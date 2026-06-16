"""Bridge for agent/module code to push custom UI blocks into the chat.

A "custom block" is an HTML file in ``<module>/blocks/<name>.html`` that the
agent can render in the chat stream as an iframe. ``push_block`` resolves the
file, serializes props, broadcasts a ``custom_block`` WS event via the active
:class:`WebUICallback`, and optionally persists a ``ChatMessage`` with role
``custom_block`` so the block survives session reloads.

The active ``WebUICallback`` is discovered in priority order:

1. Explicit ``session_id`` argument (looks up the registry).
2. The ``ContextVar`` set around the agent invocation in ``agent_executor``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from atria.core.modules import store
from atria.core.modules.registry import get_registry
from atria.models.message import ChatMessage, Role
from atria.web.protocol import WSMessageType

if TYPE_CHECKING:
    from atria.web.web_ui_callback import WebUICallback

logger = logging.getLogger(__name__)


# 256 KB cap on serialized props to keep WS frames sane.
_MAX_PROPS_BYTES = 256 * 1024


class BlockNotFound(FileNotFoundError):
    """Raised when ``blocks/<name>.html`` does not exist inside a module."""


# ── Active-callback registries ───────────────────────────────────────────────

_current_ui_callback: ContextVar[Optional["WebUICallback"]] = ContextVar(
    "_current_ui_callback", default=None
)

_callbacks_by_session: Dict[str, "WebUICallback"] = {}

# block_id -> on_event handler (kept process-wide; cleared by remove_block).
_block_event_handlers: Dict[str, Callable[[Dict[str, Any]], None]] = {}

# session_id -> (runtime_suite, web_approval_manager, working_dir) used by block_rpc
# tool.invoke. Populated by agent_executor at the start of a run; cleared at end.
_runtime_contexts_by_session: Dict[str, Dict[str, Any]] = {}


def set_runtime_context(session_id: str, ctx: Dict[str, Any]) -> None:
    if session_id:
        _runtime_contexts_by_session[session_id] = ctx


def clear_runtime_context(session_id: str) -> None:
    _runtime_contexts_by_session.pop(session_id, None)


def get_runtime_context(session_id: str) -> Optional[Dict[str, Any]]:
    return _runtime_contexts_by_session.get(session_id) if session_id else None


def set_current_ui_callback(cb: Optional["WebUICallback"]) -> None:
    """Register ``cb`` as the active callback for both the contextvar and the
    session_id-keyed registry. Pass ``None`` to clear the contextvar; the
    session-id registry is cleared separately to avoid races with concurrent
    runs from different sessions."""
    _current_ui_callback.set(cb)
    if cb is not None:
        sid = getattr(cb, "session_id", None)
        if sid:
            _callbacks_by_session[sid] = cb


def clear_session_ui_callback(session_id: str) -> None:
    """Remove the callback for ``session_id`` from the registry."""
    _callbacks_by_session.pop(session_id, None)


def get_current_ui_callback(
    session_id: Optional[str] = None,
) -> Optional["WebUICallback"]:
    """Resolve the active callback by session_id first, then by contextvar."""
    if session_id:
        cb = _callbacks_by_session.get(session_id)
        if cb is not None:
            return cb
    return _current_ui_callback.get()


# ── Block event registry ─────────────────────────────────────────────────────


def get_block_event_handler(
    block_id: str,
) -> Optional[Callable[[Dict[str, Any]], None]]:
    return _block_event_handlers.get(block_id)


def pop_block_event_handler(
    block_id: str,
) -> Optional[Callable[[Dict[str, Any]], None]]:
    return _block_event_handlers.pop(block_id, None)


# ── Internals ────────────────────────────────────────────────────────────────


def _modules_root() -> Path:
    """Match the watcher/store callers (default: ``~/.atria/modules``)."""
    return get_registry().root


def _serialize_props(props: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    obj = props or {}
    try:
        encoded = json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"block props are not JSON-serializable: {exc}") from exc
    if len(encoded.encode("utf-8")) > _MAX_PROPS_BYTES:
        raise ValueError(
            f"block props exceed {_MAX_PROPS_BYTES} bytes "
            "(256 KB cap); pass a smaller payload"
        )
    # Round-trip so callers can't smuggle in non-JSON objects.
    return json.loads(encoded)


def _require_callback(session_id: Optional[str]) -> "WebUICallback":
    cb = get_current_ui_callback(session_id)
    if cb is None:
        raise RuntimeError("no active session")
    return cb


def _publish_or_broadcast(
    session_id: Optional[str],
    envelope: Dict[str, Any],
) -> bool:
    """Send a WS envelope to whichever worker holds the session WS.

    Tries the in-process WebUICallback first (fast path). If the callback
    isn't local, falls back to the cross-process bus (Redis pubsub). Returns
    True if the message was dispatched on at least one path.
    """
    cb = get_current_ui_callback(session_id)
    if cb is not None:
        cb._broadcast(envelope)  # type: ignore[attr-defined]
        return True
    if not session_id:
        return False
    from atria.web.bus import get_bus

    bus = get_bus()
    if bus is None:
        return False
    topic = f"atria:block:{session_id}"
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(bus.publish(topic, envelope))
    except RuntimeError:
        # No running loop in this thread — schedule onto a fresh one.
        asyncio.run(bus.publish(topic, envelope))
    return True


def _persist_block_message(
    session_id: Optional[str],
    metadata: Dict[str, Any],
    cb: Optional["WebUICallback"] = None,
) -> None:
    """Append a ``custom_block``-role ChatMessage to ``session_id``.

    Prefers the callback's bound ``state`` + ``loop`` when available (fast
    path). Otherwise falls back to the process-global ``state.get_state()``
    and resolves the session by id — required when ``push_block`` is invoked
    in a worker that doesn't hold the WS for this session.
    """
    if not session_id:
        return

    state = getattr(cb, "state", None) if cb is not None else None
    loop = getattr(cb, "loop", None) if cb is not None else None

    if state is None or loop is None:
        try:
            from atria.web.state import get_state

            global_state = get_state()
            state = state or global_state
            loop = loop or getattr(global_state, "_event_loop", None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ui_bridge persist: cannot resolve global state (%s)", exc)
            return

    if state is None or loop is None or getattr(state, "session_manager", None) is None:
        logger.debug(
            "ui_bridge persist: missing state/loop/session_manager for session %s",
            session_id,
        )
        return

    async def _save() -> None:
        try:
            sess = await state.session_manager.get_session_by_id(session_id)
            if sess is None:
                return
            msg = ChatMessage(role=Role.CUSTOM_BLOCK, content="", metadata=metadata)
            sess.add_message(msg)
            await state.session_manager.save_session(sess)
        except Exception as exc:
            logger.warning("Failed to persist custom_block message: %s", exc)

    try:
        asyncio.run_coroutine_threadsafe(_save(), loop)
    except RuntimeError as exc:
        logger.warning("Could not schedule custom_block persist: %s", exc)


# ── Public API ───────────────────────────────────────────────────────────────


def push_block(
    module: str,
    block: str,
    props: Optional[Dict[str, Any]] = None,
    *,
    block_id: Optional[str] = None,
    height: Any = "auto",
    title: Optional[str] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    session_id: Optional[str] = None,
    persist: bool = True,
) -> str:
    """Render ``<module>/blocks/<block>.html`` as an iframe in the chat.

    Args:
        module: Module name (folder under ``~/.atria/modules``).
        block: Block file basename without ``.html`` extension.
        props: JSON-serializable dict passed to the iframe.
        block_id: Stable id; auto-generated if omitted.
        height: ``"auto"`` or a pixel int/string.
        title: Optional title shown above the iframe.
        on_event: Optional callback invoked when the iframe posts a
            ``block_event`` over the WS.
        session_id: Resolve target callback by session id. Falls back to the
            contextvar set around the agent invocation.
        persist: When True, also append a ``custom_block``-role ChatMessage.

    Returns:
        The resolved ``block_id``.
    """
    root = _modules_root()
    rel = f"blocks/{block}.html"
    try:
        target = store._resolve_in_module(root, module, rel)
    except ValueError as exc:
        raise BlockNotFound(f"invalid block path {rel!r}: {exc}") from exc
    if not target.is_file():
        raise BlockNotFound(f"{module}/{rel} not found")

    bid = block_id or secrets.token_hex(8)
    safe_props = _serialize_props(props)
    src = f"/api/modules/{module}/blocks/{block}.html"

    if on_event is not None:
        _block_event_handlers[bid] = on_event

    payload: Dict[str, Any] = {
        "block_id": bid,
        "module": module,
        "block": block,
        "src": src,
        "props": safe_props,
        "height": height,
        "title": title,
    }
    envelope = {
        "type": WSMessageType.CUSTOM_BLOCK,
        "data": {**payload, "session_id": session_id},
    }
    if not _publish_or_broadcast(session_id, envelope):
        raise RuntimeError("no active session")

    if persist:
        _persist_block_message(session_id, payload, cb=get_current_ui_callback(session_id))

    return bid


def update_block(
    block_id: str,
    props: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
) -> None:
    """Push a new props snapshot to an already-rendered block."""
    safe_props = _serialize_props(props)
    envelope = {
        "type": WSMessageType.CUSTOM_BLOCK_UPDATE,
        "data": {
            "block_id": block_id,
            "props": safe_props,
            "session_id": session_id,
        },
    }
    if not _publish_or_broadcast(session_id, envelope):
        raise RuntimeError("no active session")


def remove_block(
    block_id: str,
    *,
    session_id: Optional[str] = None,
) -> None:
    """Remove a previously pushed block and drop its event handler."""
    pop_block_event_handler(block_id)
    envelope = {
        "type": WSMessageType.CUSTOM_BLOCK_REMOVE,
        "data": {"block_id": block_id, "session_id": session_id},
    }
    if not _publish_or_broadcast(session_id, envelope):
        raise RuntimeError("no active session")
