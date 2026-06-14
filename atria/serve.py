"""Web server entry point — starts the Atria FastAPI server directly."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Atria web server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    parser.add_argument(
        "--working-dir",
        default=None,
        help="Working directory (default: current directory)",
    )
    args = parser.parse_args()

    working_dir = Path(args.working_dir) if args.working_dir else Path.cwd()

    from atria.core.runtime import ConfigManager, ModeManager
    from atria.core.context_engineering.history import UndoManager
    from atria.core.context_engineering.history.session_manager import PgSessionManager
    from atria.db.connection import get_sessionmaker
    from atria.db.sync import run_sync
    from atria.core.runtime.approval import ApprovalManager
    from atria.core.context_engineering.mcp.manager import MCPManager
    from atria.core.auth.pg_user_store import PgUserStore
    from atria.web import find_static_directory, start_server
    from atria.web.port_utils import find_available_port
    from rich.console import Console

    console = Console()
    config_manager = ConfigManager(working_dir)
    config = config_manager.load_config()
    _sm = run_sync(get_sessionmaker())
    session_manager = PgSessionManager(sessionmaker=_sm, working_directory=str(working_dir))
    mode_manager = ModeManager()
    approval_manager = ApprovalManager(console)
    undo_manager = UndoManager(config.max_undo_history)
    mcp_manager = MCPManager(working_dir)
    user_store = PgUserStore(_sm)

    backend_port = find_available_port(args.host, args.port, max_attempts=10)
    if backend_port is None:
        print(
            f"Error: Could not find an available port starting from {args.port}",
            file=sys.stderr,
        )
        sys.exit(1)

    static_dir = find_static_directory()
    if not static_dir or not static_dir.exists():
        print(
            "Error: Built web UI static files not found. Run `make build-ui` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    web_server_thread = start_server(
        config_manager=config_manager,
        session_manager=session_manager,
        mode_manager=mode_manager,
        approval_manager=approval_manager,
        undo_manager=undo_manager,
        user_store=user_store,
        mcp_manager=mcp_manager,
        host=args.host,
        port=backend_port,
        open_browser=False,
    )

    time.sleep(1.5)
    if not web_server_thread.is_alive():
        print("Error: Server thread terminated unexpectedly.", file=sys.stderr)
        sys.exit(1)

    print(f"Atria web UI running at http://{args.host}:{backend_port}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping Atria…")
