"""Workspace folder management: path derivation, creation, and sandbox validation."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from atria.core.paths import atria_dir


def slugify(text: str, max_length: int = 50) -> str:
    """Convert arbitrary text to a filesystem-safe slug."""
    if not text or not text.strip():
        return "untitled"
    # Normalize unicode → ASCII where possible
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    text = re.sub(r"-{2,}", "-", text)
    if not text:
        return "untitled"
    return text[:max_length].rstrip("-")


def workspace_base() -> Path:
    return atria_dir() / "workspaces"


def project_path(username: str, project_name: str) -> Path:
    return workspace_base() / slugify(username) / slugify(project_name)


def conversation_path(project_workspace: Path, conversation_name: str) -> Path:
    return project_workspace / slugify(conversation_name)


def ensure_path(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_within_workspace(path: Path, workspace: Path) -> bool:
    """Return True only if resolved path is strictly inside workspace."""
    try:
        Path(path).resolve().relative_to(Path(workspace).resolve())
        return True
    except ValueError:
        return False
