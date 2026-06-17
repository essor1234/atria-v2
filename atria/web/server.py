"""FastAPI web server for Atria UI."""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
from typing import Optional, TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from atria.web.routes import (
    chat_router,
    sessions_router,
    config_router,
    commands_router,
    mcp_router,
    auth_router,
    projects_router,
    artifacts_router,
    fs_router,
    personas_router,
    analyze_router,
    modules_router,
    blocks_router,
    module_dashboard_router,
    me_router,
    admin_tenants_router,
)
from atria.web.websocket import websocket_endpoint
from atria.core.modules.watcher import start_global_watcher, stop_global_watcher
from atria.web.state import init_state, get_state
from atria.core.runtime import ConfigManager, ModeManager
from atria.core.context_engineering.history import SessionManager, UndoManager
from atria.core.runtime.approval import ApprovalManager

if TYPE_CHECKING:
    from atria.core.context_engineering.mcp.manager import MCPManager


async def _bus_handler(topic: str, payload: dict) -> None:
    """Single subscriber callback for the message bus.

    - ``atria:block:<sid>``: re-broadcast the WS envelope to all local clients;
      the chat store on each client filters by ``session_id``.
    - ``atria:event:<bid>``: invoke the locally-registered ``on_event`` handler
      if this worker is the one that called ``push_block``.
    """
    from atria.web.websocket import ws_manager as _ws
    from atria.web.ui_bridge import get_block_event_handler

    if topic.startswith("atria:block:"):
        await _ws.broadcast(payload)
    elif topic.startswith("atria:event:"):
        bid = topic.removeprefix("atria:event:")
        handler = get_block_event_handler(bid)
        if handler is None:
            return
        try:
            handler(payload)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "block on_event handler failed (block_id=%s)", bid
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Capture event loop and ws_manager on startup for bridge mode."""
    loop = asyncio.get_event_loop()

    # Register uvicorn's loop so executor threads can schedule DB coroutines
    # onto it (avoids AsyncEngine/loop mismatch).
    from atria.db.sync import set_main_loop

    set_main_loop(loop)

    state = get_state()
    if state._event_loop is None:
        state._event_loop = loop
    from atria.web.websocket import ws_manager as _global_ws_manager

    if state.ws_manager is None:
        state.ws_manager = _global_ws_manager

    # Bootstrap the ORM schema (idempotent — only creates missing tables).
    from atria.db.connection import init_schema, get_sessionmaker

    await init_schema()

    # Ensure sessionmaker is initialized
    await get_sessionmaker()

    # Start the modules filesystem watcher: reloads the in-memory registry on
    # disk changes and broadcasts a ``modules.changed`` event to all WS clients.
    def _broadcast_modules_changed(name: str) -> None:
        coro = _global_ws_manager.broadcast({"type": "modules.changed", "name": name})
        with contextlib.suppress(RuntimeError):
            asyncio.run_coroutine_threadsafe(coro, loop)

    start_global_watcher(on_change=_broadcast_modules_changed)

    # Start the cross-process message bus.
    from atria.web.bus import make_bus, set_bus

    cfg = state.config_manager.get_config() if state.config_manager else None
    bus_cfg = cfg.web.bus if cfg else None
    bus = make_bus(
        bus_cfg.kind if bus_cfg else "in_memory",
        bus_cfg.redis_url if bus_cfg else "redis://localhost:6379/0",
    )
    bus.subscribe(_bus_handler)
    try:
        await bus.start()
        set_bus(bus)
        app.state.bus = bus
    except Exception as exc:  # noqa: BLE001
        # Don't crash startup if Redis is unreachable; degrade to no-bus mode
        # (single-process push still works via in-process callback).
        import logging

        logging.getLogger(__name__).warning(
            "Message bus startup failed (%s); push_block falls back to "
            "in-process only. Set web.bus.kind=in_memory to silence.",
            exc,
        )
        set_bus(None)
        app.state.bus = None

    # Signal that the server is ready (event loop + ws_manager are set)
    ready_event = getattr(app.state, "_ready_event", None)
    if ready_event is not None:
        ready_event.set()

    try:
        yield
    finally:
        stop_global_watcher()
        active_bus = getattr(app.state, "bus", None)
        if active_bus is not None:
            try:
                await active_bus.stop()
            except Exception:  # noqa: BLE001
                pass
        set_bus(None)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="Atria Web UI",
        description="Web interface for Atria AI coding assistant",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware for development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API routes
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(sessions_router)
    app.include_router(config_router)
    app.include_router(commands_router)
    app.include_router(mcp_router)
    app.include_router(projects_router)
    app.include_router(artifacts_router)
    app.include_router(fs_router)
    app.include_router(personas_router)
    app.include_router(analyze_router)
    app.include_router(modules_router)
    app.include_router(blocks_router)
    app.include_router(module_dashboard_router)
    app.include_router(me_router)
    app.include_router(admin_tenants_router)

    # WebSocket endpoint
    app.add_websocket_route("/ws", websocket_endpoint)

    # Health check
    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "service": "atria-web-ui"}

    # Serve static files (frontend build)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        # Mount /assets for built JS/CSS bundles
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        # Mount /static for runtime-served assets shared by custom-block iframes
        # (e.g. /static/blocks/_base.css and /static/blocks/_base.js).
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static-root")

        # SPA catch-all: serve index.html for all non-API paths
        # Registered AFTER API routes so they take priority in Starlette's route matching
        index_file = static_dir / "index.html"
        if index_file.exists():
            spa_html = index_file.read_text()

            @app.get("/{full_path:path}")
            async def serve_spa(full_path: str):
                # Serve static files (images, fonts) if they exist on disk
                file_path = static_dir / full_path
                if full_path and file_path.is_file() and not full_path.endswith(".html"):
                    from fastapi.responses import FileResponse

                    return FileResponse(str(file_path))
                return HTMLResponse(spa_html)

    else:
        # Development: Return placeholder HTML
        @app.get("/")
        async def root():
            return HTMLResponse(
                """
<!DOCTYPE html>
<html>
<head>
    <title>Atria Web UI</title>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 800px;
            margin: 100px auto;
            padding: 20px;
            background: #0f172a;
            color: #e2e8f0;
        }
        .container {
            background: #1e293b;
            padding: 40px;
            border-radius: 12px;
            border: 1px solid #334155;
        }
        h1 {
            color: #60a5fa;
            margin-bottom: 20px;
        }
        .status {
            background: #1e3a8a;
            color: #93c5fd;
            padding: 12px 20px;
            border-radius: 6px;
            margin: 20px 0;
            border: 1px solid #2563eb;
        }
        .info {
            color: #94a3b8;
            line-height: 1.8;
        }
        code {
            background: #0f172a;
            padding: 2px 8px;
            border-radius: 4px;
            color: #fbbf24;
            font-family: 'Monaco', 'Courier New', monospace;
        }
        a {
            color: #60a5fa;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .endpoints {
            margin-top: 30px;
        }
        .endpoint {
            background: #0f172a;
            padding: 10px 15px;
            margin: 8px 0;
            border-radius: 6px;
            border-left: 3px solid #10b981;
        }
        .method {
            color: #10b981;
            font-weight: bold;
            margin-right: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Atria Web UI</h1>

        <div class="status">
            ✅ Server is running
        </div>

        <div class="info">
            <p><strong>Status:</strong> Development mode</p>
            <p>The React frontend is not yet built. To develop the UI:</p>
            <ol>
                <li>Navigate to <code>web-ui/</code></li>
                <li>Run <code>npm install</code></li>
                <li>Run <code>npm run dev</code></li>
                <li>Frontend will be available at <a href="http://localhost:5173">http://localhost:5173</a></li>
            </ol>
        </div>

        <div class="endpoints">
            <h2 style="color: #60a5fa; font-size: 20px;">Available API Endpoints</h2>

            <div class="endpoint">
                <span class="method">GET</span>
                <code>/api/health</code> - Health check
            </div>

            <div class="endpoint">
                <span class="method">GET</span>
                <code>/api/chat/messages</code> - Get chat history
            </div>

            <div class="endpoint">
                <span class="method">POST</span>
                <code>/api/chat/query</code> - Send query to AI
            </div>

            <div class="endpoint">
                <span class="method">GET</span>
                <code>/api/sessions</code> - List all sessions
            </div>

            <div class="endpoint">
                <span class="method">GET</span>
                <code>/api/config</code> - Get configuration
            </div>

            <div class="endpoint">
                <span class="method">GET</span>
                <code>/api/config/providers</code> - List AI providers
            </div>

            <div class="endpoint">
                <span class="method">WS</span>
                <code>/ws</code> - WebSocket for real-time updates
            </div>
        </div>

        <p style="margin-top: 30px; color: #64748b;">
            📚 API Documentation: <a href="/docs">/docs</a>
        </p>
    </div>
</body>
</html>
            """
            )

    return app


def start_server(
    config_manager: ConfigManager,
    session_manager: SessionManager,
    mode_manager: ModeManager,
    approval_manager: ApprovalManager,
    undo_manager: UndoManager,
    user_store,
    mcp_manager: Optional["MCPManager"] = None,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
    background: bool = False,
    ready_event: Optional[threading.Event] = None,
) -> Thread:
    """Start the web server in a background thread.

    Args:
        config_manager: Configuration manager
        session_manager: Session manager
        mode_manager: Mode manager
        approval_manager: Approval manager
        undo_manager: Undo manager
        user_store: User storage backend
        mcp_manager: MCP manager (optional)
        host: Host to bind to
        port: Port to listen on
        open_browser: Whether to open browser automatically
        background: If True, run as non-daemon thread (keeps process alive)

    Returns:
        Thread running the server
    """
    # Initialize shared state
    init_state(
        config_manager,
        session_manager,
        mode_manager,
        approval_manager,
        undo_manager,
        user_store,
        mcp_manager,
    )

    # Create app
    app = create_app()

    # Attach ready event so lifespan handler can signal it
    if ready_event is not None:
        app.state._ready_event = ready_event

    # Open browser after a short delay
    if open_browser:

        def open_browser_delayed():
            import time

            time.sleep(1.5)  # Wait for server to start
            url = f"http://{host}:{port}"
            webbrowser.open(url)

        Thread(target=open_browser_delayed, daemon=True).start()

    # Run server in thread
    def run_server():
        try:
            import logging
            import warnings
            import sys

            # Suppress ALL warnings from websockets and runtime
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            warnings.filterwarnings("ignore", module="websockets")

            # Suppress all uvicorn/websockets logs to avoid polluting terminal
            logging.getLogger("uvicorn").setLevel(logging.CRITICAL)
            logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
            logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
            logging.getLogger("websockets").setLevel(logging.CRITICAL)
            logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
            logging.getLogger("websockets.legacy.server").setLevel(logging.CRITICAL)

            # DON'T suppress stderr during startup - we need to see errors
            # import io
            # sys.stderr = io.StringIO()  # Capture stderr to suppress warnings

            # Custom log config to disable all non-critical logs
            log_config = {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "default": {
                        "format": "%(message)s",
                    },
                },
                "handlers": {
                    "default": {
                        "class": "logging.NullHandler",
                    },
                },
                "loggers": {
                    "uvicorn": {"handlers": ["default"], "level": "CRITICAL"},
                    "uvicorn.error": {"handlers": ["default"], "level": "CRITICAL"},
                    "uvicorn.access": {"handlers": ["default"], "level": "CRITICAL"},
                },
            }

            # Expose the bind address so subprocess scripts (spawned by the
            # bash tool) can reach the in-process push_block HTTP gateway.
            api_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
            os.environ.setdefault("ATRIA_API_BASE", f"http://{api_host}:{port}")
            uvicorn.run(
                app,
                host=host,
                port=port,
                log_level="critical",
                access_log=False,
                log_config=log_config,
            )
        except Exception as e:
            # If there's an error starting the server, print it to stdout (not suppressed)
            import sys

            sys.stdout.write(f"\n❌ Backend server error: {e}\n")
            import traceback

            sys.stdout.write(traceback.format_exc())
            sys.stdout.flush()

    server_thread = Thread(target=run_server, daemon=not background)
    server_thread.start()

    return server_thread
