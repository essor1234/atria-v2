"""Runtime for the "Connect" subsystem: wires channel adapters to the agent.

Owns a single MessageRouter + the live TelegramAdapter instances (one per enabled
connection). Started/stopped from the FastAPI lifespan and from the Connect REST API
(enable/disable). The agent bridge runs the full Atria agent for an inbound message
and returns the reply text.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from atria.core.channels.connect_store import Connection, load_connect_config
from atria.core.channels.telegram import TelegramAdapter
from atria.core.paths import get_paths
from atria.core.runtime.approval.constants import AutonomyLevel
from atria.web.logging_config import logger
from atria.web.state import get_state

if TYPE_CHECKING:
    from atria.core.channels.router import MessageRouter


class _NoOpBroadcaster:
    """Stands in for the WebSocket manager on channel-driven turns.

    AgentExecutor broadcasts USER_MESSAGE / tool events / MESSAGE_COMPLETE to ALL
    web clients. Passing the global ws_manager would leak a Telegram chat into any
    open web UI; passing None would crash the unconditional broadcast() calls. So we
    pass an object with the same ``broadcast`` coroutine that simply discards.
    """

    async def broadcast(self, message: dict) -> None:  # noqa: D401
        return None


class ConnectManager:
    """Holds the router + adapters and the channel agent bridge."""

    def __init__(self) -> None:
        self._router: Optional[MessageRouter] = None
        self._adapters: dict[str, TelegramAdapter] = {}
        self._turn_lock = asyncio.Lock()  # serialize channel-driven agent turns

    # -- agent bridge -------------------------------------------------------

    def _default_workspace(self) -> str:
        ws = get_paths().global_dir / "workspaces" / "connect"
        ws.mkdir(parents=True, exist_ok=True)
        return str(ws)

    def _ensure_router(self) -> "MessageRouter":
        # Imported lazily to avoid a circular import: channels.router pulls in
        # session_manager, whose import chain reaches back into atria.web.
        from atria.core.channels.router import MessageRouter

        if self._router is None:
            state = get_state()
            self._router = MessageRouter(
                state.session_manager,
                self._agent_bridge,
                default_workspace=self._default_workspace(),
            )
        return self._router

    async def _agent_bridge(self, session, text: str) -> str:
        """Run the full agent for one inbound message; return the reply text.

        Channel turns are serialized (AgentExecutor mutates a global current_session)
        and run with autonomy=AUTO so the agent never blocks on an approval prompt that
        no chat user can answer.
        """
        from atria.web.agent_executor import AgentExecutor

        state = get_state()
        if getattr(state, "_agent_executor", None) is None:
            state._agent_executor = AgentExecutor(state)
        executor = state._agent_executor

        async with self._turn_lock:
            before = len(session.messages)
            prev_autonomy = state.get_autonomy_level()
            state.set_autonomy_level(AutonomyLevel.AUTO)
            try:
                await executor.execute_query(
                    text, _NoOpBroadcaster(), session_id=session.id, session=session
                )
            finally:
                state.set_autonomy_level(prev_autonomy)

        reply = ""
        for msg in session.messages[before:]:
            if getattr(msg.role, "value", "") == "assistant" and msg.content:
                reply = msg.content
        return reply or "Sorry, I couldn't produce a response to that."

    # -- adapter lifecycle --------------------------------------------------

    async def start_connection(self, conn: Connection) -> None:
        if conn.type != "telegram" or not conn.enabled or not conn.bot_token:
            return
        await self.stop_connection(conn.id)
        router = self._ensure_router()
        channel_name = f"telegram:{conn.id}"
        adapter = TelegramAdapter(
            conn.bot_token,
            channel_name=channel_name,
            router=router,
            allowed_chat_ids=conn.allowed_chat_ids(),
        )
        router.register_adapter(adapter)
        self._adapters[conn.id] = adapter
        await adapter.start()  # launches the poll loop as a background task
        logger.info("Connect: started connection %s (%s)", conn.id, channel_name)

    async def stop_connection(self, conn_id: str) -> None:
        adapter = self._adapters.pop(conn_id, None)
        if adapter is not None:
            await adapter.stop()
        if self._router is not None:
            self._router._adapters.pop(f"telegram:{conn_id}", None)

    def get_adapter(self, conn_id: str) -> Optional[TelegramAdapter]:
        return self._adapters.get(conn_id)

    def update_allowlist(self, conn: Connection) -> None:
        adapter = self._adapters.get(conn.id)
        if adapter is not None:
            adapter.update_allowlist(conn.allowed_chat_ids())

    async def start_all(self) -> None:
        cfg = load_connect_config()
        for conn in cfg.connections:
            if conn.enabled and conn.type == "telegram" and conn.bot_token:
                try:
                    await self.start_connection(conn)
                except Exception:
                    logger.exception("Connect: failed to start connection %s", conn.id)

    async def stop_all(self) -> None:
        for conn_id in list(self._adapters):
            try:
                await self.stop_connection(conn_id)
            except Exception:
                logger.exception("Connect: failed to stop connection %s", conn_id)


_connect_manager: Optional[ConnectManager] = None


def get_connect_manager() -> ConnectManager:
    global _connect_manager
    if _connect_manager is None:
        _connect_manager = ConnectManager()
    return _connect_manager
