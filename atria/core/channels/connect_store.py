"""Connection store for the "Connect" subsystem.

Persists channel connections (first type: Telegram bots) to ``~/.atria/connect.json``
(0600). Mirrors the MCP config store (``atria/core/context_engineering/mcp/config.py``)
but with its own schema. Tokens live here (gitignored ~/.atria home); the UI masks them.

A connection holds a bot token + a list of recipients (owner/manager → chat_id). The
recipients' chat_ids ARE the allowlist of who may drive the agent over that channel.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from atria.core.paths import get_paths

CONNECT_CONFIG_NAME = "connect.json"


class Recipient(BaseModel):
    """A person allowed to use a connection, by channel chat id."""

    role: str = "owner"  # "owner" | "manager"
    name: str = ""
    chat_id: str  # stored as string so it survives JSON without precision loss


class Connection(BaseModel):
    """A single channel connection (e.g. one Telegram bot)."""

    id: str
    type: str = "telegram"
    label: str = ""
    bot_token: str = ""
    enabled: bool = True
    recipients: list[Recipient] = Field(default_factory=list)

    def allowed_chat_ids(self) -> set[str]:
        """The allowlist: chat ids permitted to drive the agent."""
        return {str(r.chat_id) for r in self.recipients}


class ConnectConfig(BaseModel):
    """Root config: the list of connections."""

    connections: list[Connection] = Field(default_factory=list)

    def get(self, conn_id: str) -> Optional[Connection]:
        return next((c for c in self.connections if c.id == conn_id), None)


def get_connect_path() -> Path:
    """Path to the global connect.json (creates ~/.atria if needed)."""
    paths = get_paths()
    paths.global_dir.mkdir(parents=True, exist_ok=True)
    return paths.global_dir / CONNECT_CONFIG_NAME


def load_connect_config(path: Optional[Path] = None) -> ConnectConfig:
    """Load connect.json, returning an empty config if missing/corrupt."""
    path = path or get_connect_path()
    if not path.exists():
        return ConnectConfig()
    try:
        return ConnectConfig(**json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:  # corrupt file → don't crash the app
        print(f"Warning: failed to load connect config from {path}: {exc}")
        return ConnectConfig()


def save_connect_config(config: ConnectConfig, path: Optional[Path] = None) -> None:
    """Write connect.json (0600 — it holds bot tokens)."""
    path = path or get_connect_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(), indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX perms


def upsert_connection(connection: Connection, path: Optional[Path] = None) -> None:
    """Insert or replace a connection by id, then persist."""
    config = load_connect_config(path)
    config.connections = [c for c in config.connections if c.id != connection.id]
    config.connections.append(connection)
    save_connect_config(config, path)


def remove_connection(conn_id: str, path: Optional[Path] = None) -> bool:
    """Delete a connection by id. Returns True if one was removed."""
    config = load_connect_config(path)
    before = len(config.connections)
    config.connections = [c for c in config.connections if c.id != conn_id]
    if len(config.connections) == before:
        return False
    save_connect_config(config, path)
    return True
