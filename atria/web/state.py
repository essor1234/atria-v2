"""Shared state manager for web UI and terminal REPL."""

from __future__ import annotations

import asyncio
import logging
import threading
from queue import Queue
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Dict, List, Optional

from atria.core.context_engineering.history import UndoManager
from atria.core.auth.keycloak.services import KeycloakServices
from atria.core.auth.pg_user_store import PgUserStore
from atria.core.runtime import ConfigManager, ModeManager
from atria.core.runtime.approval import ApprovalManager
from atria.models.message import ChatMessage
from atria.models.user import User

if TYPE_CHECKING:
    from atria.core.context_engineering.mcp.manager import MCPManager

logger = logging.getLogger(__name__)


class WebState:
    """Shared state between CLI and web UI.

    This class maintains a single source of truth for:
    - Current session
    - Configuration
    - Message history
    - Agent state

    Thread-safe for concurrent access from REPL and web server.
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        session_manager: Any,
        mode_manager: ModeManager,
        approval_manager: ApprovalManager,
        undo_manager: UndoManager,
        user_store: PgUserStore,
        mcp_manager: Optional["MCPManager"] = None,
    ) -> None:
        """Initialize state with required managers."""

        self.config_manager = config_manager
        self.session_manager = session_manager
        self.mode_manager = mode_manager
        self.approval_manager = approval_manager
        self.undo_manager = undo_manager
        self.user_store = user_store
        self.mcp_manager = mcp_manager
        self.keycloak: KeycloakServices | None = KeycloakServices.from_env()
        self._current_users: Dict[str, User] = {}
        self._lock = Lock()

        # Connected WebSocket clients
        self._ws_clients: List[Any] = []

        # Pending approval requests
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}

        # Interrupt flag for stopping ongoing tasks
        self._interrupt_requested = False

        # Autonomy level for approval management
        self._autonomy_level: str = "Manual"

        # Pending ask-user requests
        self._pending_ask_users: Dict[str, Dict[str, Any]] = {}

        # Thinking level (matches TUI: Off, Low, Medium, High)
        self._thinking_level: str = "Medium"

        # Pending plan approval requests
        self._pending_plan_approvals: Dict[str, Dict[str, Any]] = {}

        # Running sessions: session_id -> "running"
        self._running_sessions: Dict[str, str] = {}

        # Live message injection queues: session_id -> Queue
        self._injection_queues: Dict[str, Queue[str]] = {}

        # Bridge mode: TUI injects messages via this callable
        self.tui_message_injector: Optional[Callable[[str, str], None]] = None

        # WebSocket manager and event loop (set by websocket/server startup)
        self.ws_manager: Optional[Any] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        # Agent executor (lazily created by websocket handler)
        self._agent_executor: Optional[Any] = None

    def add_ws_client(self, client: Any) -> None:
        """Add a WebSocket client."""
        with self._lock:
            if client not in self._ws_clients:
                self._ws_clients.append(client)

    def remove_ws_client(self, client: Any) -> None:
        """Remove a WebSocket client."""
        with self._lock:
            if client in self._ws_clients:
                self._ws_clients.remove(client)

    def get_ws_clients(self) -> List[Any]:
        """Get all connected WebSocket clients."""
        with self._lock:
            return self._ws_clients.copy()

    async def get_messages(self) -> List[ChatMessage]:
        """Get current session messages."""
        session = await self.session_manager.get_current_session()
        if session:
            return session.messages
        return []

    async def add_message(self, message: ChatMessage) -> None:
        """Add a message to current session."""
        await self.session_manager.add_message(message)

    async def get_current_session_id(self) -> Optional[str]:
        """Get current session ID."""
        session = await self.session_manager.get_current_session()
        return session.id if session else None

    async def resume_session(self, session_id: str, owner_id: str) -> bool:
        """Resume the given session if owned by the user or unowned."""
        try:
            session = await self.session_manager.load_session(session_id, owner_id=owner_id)
        except FileNotFoundError:
            return False
        if session.owner_id is not None and session.owner_id != owner_id:
            return False
        return True

    async def list_sessions(self, owner_id: str) -> List[Dict[str, Any]]:
        """List sessions owned by the user or unowned (TUI-created) across all workspaces."""
        sessions = []
        for session_meta in await self.session_manager.list_all_sessions(
            owner_id=owner_id, include_unowned=True
        ):
            sessions.append(
                {
                    "id": session_meta.id,
                    "working_dir": session_meta.working_directory or "",
                    "created_at": session_meta.created_at.isoformat(),
                    "updated_at": session_meta.updated_at.isoformat(),
                    "message_count": session_meta.message_count,
                    "total_tokens": session_meta.total_tokens,
                    "title": session_meta.title,
                    "has_session_model": session_meta.has_session_model,
                    "channel": session_meta.channel,
                    "channel_user_id": session_meta.channel_user_id,
                    "thread_id": session_meta.thread_id,
                }
            )
        return sessions

    def add_pending_approval(
        self,
        approval_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        session_id: Optional[str] = None,
        event: Optional[threading.Event] = None,
    ) -> None:
        """Add a pending approval request."""
        with self._lock:
            self._pending_approvals[approval_id] = {
                "tool_name": tool_name,
                "arguments": arguments,
                "resolved": False,
                "approved": None,
                "session_id": session_id,
                "_event": event,
            }
        self._schedule_async(
            self._persist_pending(
                "approval",
                approval_id,
                session_id,
                {"tool_name": tool_name, "arguments": arguments},
            )
        )

    def resolve_approval(
        self, approval_id: str, approved: bool, auto_approve: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Resolve a pending approval request. Returns approval data or None."""
        with self._lock:
            if approval_id in self._pending_approvals:
                approval = self._pending_approvals[approval_id]
                approval["resolved"] = True
                approval["approved"] = approved
                approval["auto_approve"] = auto_approve
                # Snapshot data before event.set() wakes the agent thread
                data = {k: v for k, v in approval.items() if k != "_event"}
                event = approval.get("_event")
                if event:
                    event.set()
                return data
            return None

    def get_pending_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Get a pending approval request."""
        with self._lock:
            return self._pending_approvals.get(approval_id)

    def clear_approval(self, approval_id: str) -> None:
        """Clear a resolved approval."""
        with self._lock:
            self._pending_approvals.pop(approval_id, None)

    def clear_session_approvals(self, session_id: str) -> None:
        """Clear all pending approvals for a session."""
        with self._lock:
            to_remove = [
                aid
                for aid, a in self._pending_approvals.items()
                if a.get("session_id") == session_id
            ]
            for aid in to_remove:
                approval = self._pending_approvals.pop(aid)
                # Wake any blocked threads so they don't hang
                if not approval.get("resolved"):
                    approval["resolved"] = True
                    approval["approved"] = False
                    event = approval.get("_event")
                    if event:
                        event.set()

    def request_interrupt(self) -> None:
        """Request interruption of ongoing task."""
        with self._lock:
            self._interrupt_requested = True
            # Wake up any threads blocked on approval waits
            for approval in self._pending_approvals.values():
                if not approval.get("resolved"):
                    approval["resolved"] = True
                    approval["approved"] = False
                    event = approval.get("_event")
                    if event:
                        event.set()

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        with self._lock:
            self._interrupt_requested = False

    def is_interrupt_requested(self) -> bool:
        """Check if interrupt has been requested."""
        with self._lock:
            return self._interrupt_requested

    # --- Autonomy level ---

    def get_autonomy_level(self) -> str:
        """Get current autonomy level."""
        with self._lock:
            return self._autonomy_level

    def set_autonomy_level(self, level: str) -> None:
        """Set autonomy level."""
        with self._lock:
            self._autonomy_level = level

    # --- Thinking level ---

    def get_thinking_level(self) -> str:
        """Get current thinking level."""
        with self._lock:
            return self._thinking_level

    def set_thinking_level(self, level: str) -> None:
        """Set thinking level."""
        with self._lock:
            self._thinking_level = level

    # --- Running sessions ---

    def set_session_running(self, session_id: str) -> None:
        """Mark a session as having a running agent."""
        with self._lock:
            self._running_sessions[session_id] = "running"

    def set_session_idle(self, session_id: str) -> None:
        """Mark a session as idle (no running agent)."""
        with self._lock:
            self._running_sessions.pop(session_id, None)

    def is_session_running(self, session_id: str) -> bool:
        """Check if a session has a running agent."""
        with self._lock:
            return session_id in self._running_sessions

    # --- Injection queues ---

    def get_injection_queue(self, session_id: str) -> Queue[str]:
        """Get or create the injection queue for a session."""
        with self._lock:
            if session_id not in self._injection_queues:
                self._injection_queues[session_id] = Queue(maxsize=10)
            return self._injection_queues[session_id]

    def clear_injection_queue(self, session_id: str) -> None:
        """Remove the injection queue for a session."""
        with self._lock:
            self._injection_queues.pop(session_id, None)

    # --- Bridge mode ---

    @property
    def is_bridge_mode(self) -> bool:
        """True when TUI is the execution authority and Web UI mirrors it."""
        return self.tui_message_injector is not None

    def get_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get the event loop used by the web server."""
        return self._event_loop

    # --- Ask-user state ---

    def add_pending_ask_user(
        self,
        request_id: str,
        data: Dict[str, Any],
        session_id: Optional[str] = None,
        event: Optional[threading.Event] = None,
    ) -> None:
        """Add a pending ask-user request."""
        with self._lock:
            self._pending_ask_users[request_id] = {
                "data": data,
                "resolved": False,
                "answers": None,
                "cancelled": False,
                "session_id": session_id,
                "_event": event,
            }
        self._schedule_async(self._persist_pending("ask_user", request_id, session_id, data))

    def resolve_ask_user(
        self, request_id: str, answers: Optional[Dict], cancelled: bool = False
    ) -> bool:
        """Resolve a pending ask-user request."""
        with self._lock:
            if request_id in self._pending_ask_users:
                self._pending_ask_users[request_id]["resolved"] = True
                self._pending_ask_users[request_id]["answers"] = answers
                self._pending_ask_users[request_id]["cancelled"] = cancelled
                event = self._pending_ask_users[request_id].get("_event")
                if event:
                    event.set()
                return True
            return False

    def get_pending_ask_user(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get a pending ask-user request."""
        with self._lock:
            return self._pending_ask_users.get(request_id)

    def clear_ask_user(self, request_id: str) -> None:
        """Clear a resolved ask-user request."""
        with self._lock:
            self._pending_ask_users.pop(request_id, None)

    # --- Plan approval state ---

    def add_pending_plan_approval(
        self,
        request_id: str,
        data: Dict[str, Any],
        session_id: Optional[str] = None,
        event: Optional[threading.Event] = None,
    ) -> None:
        """Add a pending plan approval request."""
        with self._lock:
            self._pending_plan_approvals[request_id] = {
                "data": data,
                "resolved": False,
                "action": None,
                "feedback": "",
                "session_id": session_id,
                "_event": event,
            }
        self._schedule_async(self._persist_pending("plan_approval", request_id, session_id, data))

    def resolve_plan_approval(self, request_id: str, action: str, feedback: str = "") -> bool:
        """Resolve a pending plan approval request."""
        with self._lock:
            if request_id in self._pending_plan_approvals:
                self._pending_plan_approvals[request_id]["resolved"] = True
                self._pending_plan_approvals[request_id]["action"] = action
                self._pending_plan_approvals[request_id]["feedback"] = feedback
                event = self._pending_plan_approvals[request_id].get("_event")
                if event:
                    event.set()
                return True
            return False

    def get_pending_plan_approval(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get a pending plan approval request."""
        with self._lock:
            return self._pending_plan_approvals.get(request_id)

    def clear_plan_approval(self, request_id: str) -> None:
        """Clear a resolved plan approval request."""
        with self._lock:
            self._pending_plan_approvals.pop(request_id, None)

    # ──────────────────────────────────────────────────────────────────
    # Persistence for pending reviews
    #
    # The 4 _pending_* dicts above hold a threading.Event so the producing
    # agent thread can block waiting for a resolution from the WS. Events
    # are memory-only — if the process restarts, the waiter is gone and
    # any in-flight request_id the UI still holds resolves to "not found".
    #
    # The helpers below mirror each add/resolve into the `pending_reviews`
    # Postgres table. After a restart the agent that asked the question is
    # dead, but the user's click on Apply / Approve still updates a real
    # row and the WS handler returns success instead of an error.
    # ──────────────────────────────────────────────────────────────────

    def _schedule_async(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Fire-and-forget a coroutine onto the saved web event loop.

        Called from sync agent threads (producers) where we don't want to
        introduce a new blocking I/O step. Silently dropped if the loop
        isn't ready yet — persistence is best-effort.
        """
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError as exc:
            logger.warning("Failed to schedule pending-review persistence: %s", exc)

    async def _persist_pending(
        self,
        kind: str,
        request_id: str,
        session_id: Optional[str],
        request_data: Optional[Dict[str, Any]],
    ) -> None:
        try:
            from atria.db.connection import get_sessionmaker
            from atria.db.repositories.pending_review_repo import PendingReviewRepository

            sm = await get_sessionmaker()
            repo = PendingReviewRepository(sm)
            await repo.upsert(
                request_id=request_id,
                kind=kind,
                session_id=session_id,
                user_id=None,
                request_data=request_data,
            )
        except Exception as exc:  # never crash the agent thread
            logger.warning("Pending review persist failed (%s/%s): %s", kind, request_id, exc)

    async def _persist_resolution(
        self,
        request_id: str,
        response_data: Dict[str, Any],
    ) -> bool:
        try:
            from atria.db.connection import get_sessionmaker
            from atria.db.repositories.pending_review_repo import PendingReviewRepository

            sm = await get_sessionmaker()
            repo = PendingReviewRepository(sm)
            return await repo.resolve(request_id, response_data)
        except Exception as exc:
            logger.warning("Pending review resolve persist failed (%s): %s", request_id, exc)
            return False

    async def aresolve_approval(
        self, approval_id: str, approved: bool, auto_approve: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Resolve an approval; falls back to DB if memory dict was wiped."""
        data = self.resolve_approval(approval_id, approved, auto_approve)
        response = {
            "approved": approved,
            "auto_approve": auto_approve,
        }
        db_ok = await self._persist_resolution(approval_id, response)
        if data is not None:
            return data
        if db_ok:
            return {"resolved": True, "approved": approved, "auto_approve": auto_approve}
        return None

    async def aresolve_ask_user(
        self, request_id: str, answers: Optional[Dict], cancelled: bool = False
    ) -> bool:
        ok = self.resolve_ask_user(request_id, answers, cancelled)
        response = {"answers": answers, "cancelled": cancelled}
        db_ok = await self._persist_resolution(request_id, response)
        return ok or db_ok

    async def aresolve_plan_approval(
        self, request_id: str, action: str, feedback: str = ""
    ) -> bool:
        ok = self.resolve_plan_approval(request_id, action, feedback)
        response = {"action": action, "feedback": feedback}
        db_ok = await self._persist_resolution(request_id, response)
        return ok or db_ok

    async def get_git_branch(self) -> Optional[str]:
        """Get current git branch for the working directory."""
        import subprocess

        try:
            session = await self.session_manager.get_current_session()
            cwd = session.working_directory if session else None
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=3,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None


# Global state instance (will be initialized when web server starts)
_state: Optional[WebState] = None


def init_state(
    config_manager: ConfigManager,
    session_manager: Any,
    mode_manager: ModeManager,
    approval_manager: ApprovalManager,
    undo_manager: UndoManager,
    user_store: PgUserStore,
    mcp_manager: Optional["MCPManager"] = None,
) -> WebState:
    """Initialize the global state instance."""
    global _state
    _state = WebState(
        config_manager,
        session_manager,
        mode_manager,
        approval_manager,
        undo_manager,
        user_store,
        mcp_manager,
    )
    return _state


def get_state() -> WebState:
    """Get the global state instance."""
    if _state is None:
        # Auto-initialize with default managers for standalone server
        from pathlib import Path
        from atria.core.runtime import ConfigManager, ModeManager
        from atria.core.context_engineering.history import UndoManager
        from atria.core.context_engineering.history.session_manager import PgSessionManager
        from atria.core.auth.pg_user_store import PgUserStore
        from atria.db.connection import get_sessionmaker, init_schema
        from atria.db.sync import run_sync
        from atria.core.runtime.approval import ApprovalManager
        from atria.core.context_engineering.mcp.manager import MCPManager
        from rich.console import Console

        console = Console()
        working_dir = Path.cwd()

        config_manager = ConfigManager(working_dir)
        sm = run_sync(get_sessionmaker())
        run_sync(init_schema())
        session_manager = PgSessionManager(sessionmaker=sm, working_directory=str(working_dir))
        mode_manager = ModeManager()
        approval_manager = ApprovalManager(console)
        undo_manager = UndoManager(50)
        user_store = PgUserStore(sm)

        # Initialize MCP manager
        mcp_manager = MCPManager(working_dir)

        # Don't create session on startup - let user create via UI

        return init_state(
            config_manager,
            session_manager,
            mode_manager,
            approval_manager,
            undo_manager,
            user_store,
            mcp_manager,
        )
    return _state


async def broadcast_to_all_clients(message: Dict[str, Any]) -> None:
    """Broadcast a message to all connected WebSocket clients.

    Args:
        message: Message to broadcast (will be JSON-serialized)
    """
    state = get_state()
    clients = state.get_ws_clients()

    import json

    for client in clients:
        try:
            await client.send_text(json.dumps(message))
        except Exception:
            # Client disconnected, will be cleaned up by WebSocket handler
            pass
