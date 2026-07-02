"""WebSocket handler for real-time communication."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from atria.web.state import get_state
from atria.web.logging_config import logger
from atria.web.protocol import WSMessageType
from atria.models.message import ChatMessage, Role
from atria.web.routes.auth import TOKEN_COOKIE, verify_token
from atria.web.web_ui_callback import _BLOCK_FEED_EVENT_TYPES


class WebSocketManager:
    """Manages WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._block_feed_subs: Dict[str, set] = {}

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        state = get_state()
        state.add_ws_client(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        state = get_state()
        state.remove_ws_client(websocket)

    async def send_message(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")
            logger.error(f"Message type: {message.get('type')}")
            self.disconnect(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            logger.debug("Broadcast to 0 clients: type=%s", message.get("type"))
            return

        # Validate message is JSON-serializable before broadcasting
        try:
            import json

            json.dumps(message)
            if message.get("type") != WSMessageType.THINKING_DONE and message.get("type") != WSMessageType.THINKING_TOKEN:
                logger.debug(f"Broadcasting: {message.get('type')}")
        except (TypeError, ValueError) as e:
            logger.error(f"❌ Message is not JSON-serializable: {e}")
            logger.error(f"Message type: {message.get('type')}")
            logger.error(f"Message keys: {list(message.keys())}")
            # Try to send error message instead
            error_message = {
                "type": "error",
                "data": {"message": f"Internal serialization error: {str(e)}"},
            }
            message = error_message

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Failed to broadcast to connection: {e}")
                logger.error(f"Message type: {message.get('type')}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    def forward_to_block_feed(self, session_id: str, event: str, data: Dict[str, Any]) -> None:
        """Emit a block_event_feed message for every block subscribed in this session."""
        import asyncio as _asyncio

        subs = self._block_feed_subs.get(session_id)
        if not subs:
            return
        for block_id in list(subs):
            msg = {
                "type": "block_event_feed",
                "data": {"block_id": block_id, "event": event, "data": data,
                         "session_id": session_id},
            }
            try:
                loop = _asyncio.get_running_loop()
                loop.create_task(self.broadcast(msg))
            except RuntimeError:
                _asyncio.run(self.broadcast(msg))

    async def handle_message(self, websocket: WebSocket, data: Dict[str, Any]):
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")
        if msg_type != "ping":
            logger.debug(f"Received WebSocket message: type={msg_type}")

        if msg_type == "query":
            await self._handle_query(websocket, data)
        elif msg_type == "approve":
            await self._handle_approval(websocket, data)
        elif msg_type == "ask_user_response":
            await self._handle_ask_user_response(websocket, data)
        elif msg_type == "plan_approval_response":
            await self._handle_plan_approval_response(websocket, data)
        elif msg_type == "block_event":
            await self._handle_block_event(websocket, data)
        elif msg_type == "block_rpc":
            await self._handle_block_rpc(websocket, data)
        elif msg_type == "ping":
            await self.send_message(websocket, {"type": WSMessageType.PONG})
        else:
            logger.warning(f"Unknown message type: {msg_type}")
            await self.send_message(
                websocket,
                {
                    "type": WSMessageType.ERROR,
                    "data": {"message": f"Unknown message type: {msg_type}"},
                },
            )

    async def _handle_query(self, websocket: WebSocket, data: Dict[str, Any]):
        """Handle a query message."""
        import asyncio

        message = data.get("data", {}).get("message")
        session_id = data.get("data", {}).get("session_id")
        persona_name = data.get("data", {}).get("persona_name")
        # Reject persona_name with path traversal sequences
        if persona_name and (
            not isinstance(persona_name, str) or "/" in persona_name or ".." in persona_name
        ):
            persona_name = None

        if not message:
            await self.send_message(
                websocket,
                {"type": WSMessageType.ERROR, "data": {"message": "Missing message field"}},
            )
            return

        state = get_state()

        # Resolve session_id: use provided, fall back to current
        if not session_id:
            session_id = await state.get_current_session_id()
        if not session_id:
            await self.send_message(
                websocket, {"type": WSMessageType.ERROR, "data": {"message": "No active session"}}
            )
            return

        # Bridge mode: route to TUI's message processor instead of AgentExecutor
        if state.is_bridge_mode:
            # Broadcast user message to all WS clients
            await self.broadcast(
                {
                    "type": WSMessageType.USER_MESSAGE,
                    "data": {
                        "role": "user",
                        "content": message,
                        "session_id": session_id,
                    },
                }
            )
            # Inject into TUI's message processor
            try:
                state.tui_message_injector(message, session_id)
            except Exception as e:
                logger.error(f"Bridge mode injection failed: {e}")
                await self.send_message(
                    websocket,
                    {
                        "type": "error",
                        "data": {"message": f"Failed to inject message: {e}"},
                    },
                )
            return

        # If session is already running, inject message into the agent loop
        if state.is_session_running(session_id):
            injection_queue = state.get_injection_queue(session_id)
            import queue as queue_mod

            try:
                injection_queue.put_nowait(message)
            except queue_mod.Full:
                await self.send_message(
                    websocket,
                    {
                        "type": "error",
                        "data": {
                            "message": "Injection queue full, message dropped",
                            "session_id": session_id,
                        },
                    },
                )
                return
            # Broadcast injected user message (EC5: no session persistence here)
            await self.broadcast(
                {
                    "type": WSMessageType.USER_MESSAGE,
                    "data": {
                        "role": "user",
                        "content": message,
                        "session_id": session_id,
                        "injected": True,
                    },
                }
            )
            return

        # Resolve current user from the WebSocket scope (set in websocket_endpoint).
        ws_user = websocket.scope.get("user")
        owner_id = str(ws_user.id) if ws_user is not None else None

        # Load session without mutating current_session, scoped to the caller.
        try:
            session = await state.session_manager.get_session_by_id(session_id, owner_id=owner_id)
        except FileNotFoundError:
            # Fallback: session may be newly created but not yet on disk
            current = await state.session_manager.get_current_session()
            if (
                current
                and current.id == session_id
                and (owner_id is None or current.owner_id is None or current.owner_id == owner_id)
            ):
                session = current
            else:
                await self.send_message(
                    websocket,
                    {
                        "type": "error",
                        "data": {"message": f"Session {session_id} not found"},
                    },
                )
                return

        # Add user message directly to the session object
        user_msg = ChatMessage(role=Role.USER, content=message)
        session.add_message(user_msg)
        await state.session_manager.save_session(session)

        # Broadcast user message with session_id
        await self.broadcast(
            {
                "type": WSMessageType.USER_MESSAGE,
                "data": {
                    "role": "user",
                    "content": message,
                    "session_id": session_id,
                },
            }
        )

        # Execute query with agent using shared executor (singleton on state)
        from atria.web.agent_executor import AgentExecutor

        if not hasattr(state, "_agent_executor") or state._agent_executor is None:
            state._agent_executor = AgentExecutor(state)
        executor = state._agent_executor
        asyncio.create_task(
            executor.execute_query(
                message, self, session_id=session_id, session=session, persona_name=persona_name
            )
        )

    async def _handle_approval(self, websocket: WebSocket, data: Dict[str, Any]):
        """Handle an approval response from the web UI."""
        logger.info(f"Received approval response: {data}")
        approval_data = data.get("data", {})
        approval_id = approval_data.get("approvalId")
        approved = approval_data.get("approved")
        auto_approve = approval_data.get("autoApprove", False)

        logger.info(f"Approval: id={approval_id}, approved={approved}, auto={auto_approve}")

        if approval_id is None or approved is None:
            logger.error(f"Invalid approval data: {approval_data}")
            await self.send_message(
                websocket,
                {"type": WSMessageType.ERROR, "data": {"message": "Invalid approval data"}},
            )
            return

        # Resolve the approval in shared state (memory + DB fallback)
        state = get_state()
        resolved = await state.aresolve_approval(approval_id, approved, auto_approve)

        if not resolved:
            logger.warning(f"Approval {approval_id} not found (already processed or timed out)")
            return

        logger.info(f"✓ Approval {approval_id} resolved successfully")
        resolved_session_id = resolved.get("session_id")
        # Broadcast the resolution to all clients
        await self.broadcast(
            {
                "type": WSMessageType.APPROVAL_RESOLVED,
                "data": {
                    "approvalId": approval_id,
                    "approved": approved,
                    "session_id": resolved_session_id,
                },
            }
        )

    async def _handle_ask_user_response(self, websocket: WebSocket, data: Dict[str, Any]):
        """Handle an ask-user response from the web UI."""
        logger.info(f"Received ask-user response: {data}")
        response_data = data.get("data", {})
        request_id = response_data.get("requestId")
        answers = response_data.get("answers")
        cancelled = response_data.get("cancelled", False)

        if not request_id:
            logger.error(f"Invalid ask-user response data: {response_data}")
            await self.send_message(
                websocket,
                {
                    "type": WSMessageType.ERROR,
                    "data": {"message": "Invalid ask-user response data"},
                },
            )
            return

        state = get_state()
        success = await state.aresolve_ask_user(request_id, answers, cancelled)

        if not success:
            logger.error(f"Ask-user request {request_id} not found in state")
            await self.send_message(
                websocket,
                {
                    "type": WSMessageType.ERROR,
                    "data": {"message": f"Ask-user request {request_id} not found"},
                },
            )
            return

        logger.info(f"✓ Ask-user {request_id} resolved")
        # Retrieve session_id from the pending ask-user request
        pending = state.get_pending_ask_user(request_id)
        resolved_session_id = pending.get("session_id") if pending else None
        await self.broadcast(
            {
                "type": WSMessageType.ASK_USER_RESOLVED,
                "data": {"requestId": request_id, "session_id": resolved_session_id},
            }
        )

    async def _handle_plan_approval_response(self, websocket: WebSocket, data: Dict[str, Any]):
        """Handle a plan approval response from the web UI."""
        logger.info(f"Received plan approval response: {data}")
        response_data = data.get("data", {})
        request_id = response_data.get("requestId")
        action = response_data.get("action", "reject")
        feedback = response_data.get("feedback", "")

        if not request_id:
            logger.error(f"Invalid plan approval response data: {response_data}")
            await self.send_message(
                websocket,
                {
                    "type": WSMessageType.ERROR,
                    "data": {"message": "Invalid plan approval response data"},
                },
            )
            return

        state = get_state()
        success = await state.aresolve_plan_approval(request_id, action, feedback)

        if not success:
            logger.error(f"Plan approval request {request_id} not found in state")
            await self.send_message(
                websocket,
                {
                    "type": "error",
                    "data": {"message": f"Plan approval request {request_id} not found"},
                },
            )
            return

        logger.info(f"✓ Plan approval {request_id} resolved: action={action}")
        pending = state.get_pending_plan_approval(request_id)
        resolved_session_id = pending.get("session_id") if pending else None
        await self.broadcast(
            {
                "type": WSMessageType.PLAN_APPROVAL_RESOLVED,
                "data": {
                    "requestId": request_id,
                    "action": action,
                    "session_id": resolved_session_id,
                },
            }
        )

    # ------------------------------------------------------------------
    # Custom block iframe channel
    # ------------------------------------------------------------------

    async def _handle_block_event(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Forward an iframe-emitted event to the registered on_event handler."""
        payload = data.get("data") or data
        block_id = payload.get("block_id")
        name = payload.get("name")
        event_data = payload.get("data")

        if not block_id or not name:
            logger.warning(f"block_event missing block_id/name: {payload}")
            return

        from atria.web import ui_bridge

        envelope = {"name": name, "data": event_data, "block_id": block_id}
        handler = ui_bridge.get_block_event_handler(block_id)
        if handler is not None:
            try:
                handler(envelope)
            except Exception as exc:
                logger.error(f"block_event handler raised: {exc}", exc_info=True)
            return

        # No local handler — the on_event was registered in a different worker.
        # Publish on the bus so whichever worker holds the handler receives it.
        from atria.web.bus import get_bus

        bus = get_bus()
        if bus is None:
            logger.debug(f"block_event for unknown block_id={block_id}; no bus; dropping")
            return
        try:
            await bus.publish(f"atria:event:{block_id}", envelope)
        except Exception as exc:
            logger.error(f"block_event bus publish failed: {exc}", exc_info=True)

    async def _handle_block_rpc(self, websocket: WebSocket, data: Dict[str, Any]) -> None:
        """Dispatch an iframe RPC call against the active session's runtime."""
        import asyncio as _asyncio

        payload = data.get("data") or data
        block_id = payload.get("block_id")
        req_id = payload.get("req_id")
        method = payload.get("method")
        args = payload.get("args") or {}
        session_id = payload.get("session_id")

        async def _reply(ok: bool, *, data: Any = None, error: str = "") -> None:
            msg = {
                "type": "block_rpc_result",
                "data": {
                    "block_id": block_id,
                    "req_id": req_id,
                    "ok": ok,
                },
            }
            if ok:
                msg["data"]["data"] = data
            else:
                msg["data"]["error"] = error
            await self.broadcast(msg)

        if not block_id or not req_id or not method:
            await _reply(False, error="missing required fields")
            return

        # Allowlist check
        state = get_state()
        try:
            app_config = state.config_manager.get_config()
            allowlist = list(app_config.web.iframe_rpc.tool_allowlist or [])
        except Exception:
            allowlist = []

        if method not in allowlist:
            await _reply(False, error="method_not_allowed")
            return

        # Resolve runtime context (for tool.invoke / session.send_user_message)
        from atria.web import ui_bridge

        if not session_id:
            session_id = await state.get_current_session_id()
        runtime_ctx = ui_bridge.get_runtime_context(session_id) if session_id else None

        def _run_sync() -> Dict[str, Any]:
            """Synchronous dispatcher running off-thread with a 5s timeout."""
            if method == "tool.invoke":
                if runtime_ctx is None:
                    raise RuntimeError("no active runtime context for tool.invoke")
                tool_name = args.get("name")
                tool_args = args.get("args") or {}
                if not tool_name:
                    raise ValueError("tool.invoke requires 'name'")
                registry = runtime_ctx["tool_registry"]
                result = registry.execute_tool(
                    tool_name,
                    tool_args,
                    mode_manager=state.mode_manager,
                    approval_manager=runtime_ctx.get("approval_manager"),
                    undo_manager=state.undo_manager,
                    session_manager=state.session_manager,
                    ui_callback=runtime_ctx.get("ui_callback"),
                )
                return result

            if method == "artifact.read":
                artifact_id = args.get("artifact_id")
                if artifact_id is None:
                    raise ValueError("artifact.read requires 'artifact_id'")
                from atria.core.context_engineering.tools.context import ToolExecutionContext
                from atria.core.context_engineering.tools.handlers.artifacts_handler import (
                    ArtifactsHandler,
                )

                handler = ArtifactsHandler()
                ctx = ToolExecutionContext(session_manager=state.session_manager)
                return handler.read_artifact_image({"artifact_id": artifact_id}, ctx)

            if method == "config.read":
                app_config = state.config_manager.get_config()
                allowed_keys = set(app_config.web.iframe_rpc.config_read_keys or [])
                requested = args.get("keys") or list(allowed_keys)
                out: Dict[str, Any] = {}
                for k in requested:
                    if k in allowed_keys:
                        out[k] = getattr(app_config, k, None)
                return out

            raise ValueError(f"unsupported method: {method}")

        async def _dispatch() -> None:
            if method == "events.subscribe":
                if not session_id:
                    await _reply(False, error="no active session")
                    return
                requested = args.get("events")
                if requested:
                    subscribed = [
                        e for e in requested if e in _BLOCK_FEED_EVENT_TYPES
                    ]
                else:
                    subscribed = list(_BLOCK_FEED_EVENT_TYPES)
                self._block_feed_subs.setdefault(
                    session_id, set()
                ).add(block_id)
                await _reply(True, data={"subscribed": subscribed})
                return

            if method == "session.send_user_message":
                text = args.get("text")
                if not text or not isinstance(text, str):
                    await _reply(False, error="session.send_user_message requires 'text'")
                    return
                if not session_id:
                    await _reply(False, error="no active session")
                    return
                try:
                    session = await state.session_manager.get_session_by_id(session_id)
                    user_msg = ChatMessage(role=Role.USER, content=text)
                    session.add_message(user_msg)
                    await state.session_manager.save_session(session)
                    await self.broadcast(
                        {
                            "type": WSMessageType.USER_MESSAGE,
                            "data": {
                                "role": "user",
                                "content": text,
                                "session_id": session_id,
                                "injected": True,
                            },
                        }
                    )
                    await _reply(True, data={"injected": True})
                except Exception as exc:
                    await _reply(False, error=str(exc))
                return

            if method in ("chat.get_messages", "chat.get_session"):
                if not session_id:
                    await _reply(False, error="no active session")
                    return
                try:
                    session = await state.session_manager.get_session_by_id(session_id)
                except Exception as exc:  # noqa: BLE001
                    await _reply(False, error=str(exc))
                    return
                if session is None:
                    await _reply(False, error="session not found")
                    return
                if method == "chat.get_session":
                    await _reply(True, data={
                        "session_id": session_id,
                        "title": getattr(session, "title", None),
                        "message_count": len(session.messages),
                    })
                    return
                limit = args.get("limit")
                msgs = session.messages
                if isinstance(limit, int) and limit > 0:
                    msgs = msgs[-limit:]
                await _reply(True, data={
                    "messages": [m.model_dump(mode="json") for m in msgs],
                })
                return

            if method == "artifact.list":
                try:
                    from atria.core.context_engineering.tools.context import ToolExecutionContext
                    from atria.core.context_engineering.tools.handlers.artifacts_handler import (
                        ArtifactsHandler,
                    )

                    handler = ArtifactsHandler()
                    ctx = ToolExecutionContext(session_manager=state.session_manager)
                    scope = args.get("scope", "conversation")
                    result = await _asyncio.to_thread(
                        handler.list_artifact_images, {"scope": scope}, ctx
                    )
                    await _reply(True, data=result)
                except Exception as exc:  # noqa: BLE001
                    await _reply(False, error=str(exc))
                return

            # tool.invoke and artifact.read run synchronously off-thread
            try:
                result = await _asyncio.wait_for(_asyncio.to_thread(_run_sync), timeout=5.0)
                await _reply(True, data=result)
            except _asyncio.TimeoutError:
                await _reply(False, error="timeout")
            except Exception as exc:
                logger.error(f"block_rpc {method} failed: {exc}", exc_info=True)
                await _reply(False, error=str(exc))

        await _dispatch()


# Global WebSocket manager instance
ws_manager = WebSocketManager()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint handler."""
    token = websocket.cookies.get(TOKEN_COOKIE)
    if token:
        try:
            user_id_str = verify_token(token)
            state = get_state()
            user = await state.user_store.get_by_id(int(user_id_str))
            if user:
                websocket.scope["user"] = user
        except Exception:
            pass  # Fall through to unauthenticated connection

    logger.info("New WebSocket connection established")

    # Store ws_manager and event loop on state for bridge mode access
    state = get_state()
    if state.ws_manager is None:
        state.ws_manager = ws_manager
    if state._event_loop is None:
        state._event_loop = asyncio.get_event_loop()

    await ws_manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "ping":
                logger.debug(f"Raw message received: {data}")
            await ws_manager.handle_message(websocket, data)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected normally")
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        import traceback

        logger.error(traceback.format_exc())
        ws_manager.disconnect(websocket)
