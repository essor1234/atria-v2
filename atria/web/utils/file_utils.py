"""File utility functions for artifact uploads."""

from __future__ import annotations

import re
import uuid
from pathlib import Path


def sanitize_filename(filename: str) -> str:
    """Remove dangerous characters from filename.

    Removes path separators, null bytes, and other problematic characters
    to prevent directory traversal attacks.

    Args:
        filename: The original filename to sanitize.

    Returns:
        Sanitized filename safe for filesystem use.
    """
    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Remove path separators (forward and back slashes)
    filename = filename.replace("/", "").replace("\\", "")

    # Remove leading dots to prevent hidden files
    filename = filename.lstrip(".")

    # Remove other problematic characters but allow spaces, underscores, hyphens
    filename = re.sub(r'[<>:"|?*]', "", filename)

    # If filename is empty after sanitization, use a default
    if not filename:
        filename = "file"

    return filename


def generate_safe_filename(original: str) -> str:
    """Generate a filename with UUID prefix to prevent collisions.

    Args:
        original: The original filename.

    Returns:
        A filename with UUID prefix (format: {uuid_prefix}_{original}).
    """
    sanitized = sanitize_filename(original)
    uuid_prefix = uuid.uuid4().hex[:8]
    return f"{uuid_prefix}_{sanitized}"


def get_artifact_dir(
    conversation_id: int | None,
    working_dir: str,
    scope: str = "conversation",
) -> str:
    """Get the artifact directory path for conversation or project scope.

    Args:
        conversation_id: The conversation ID (required for conversation scope).
        working_dir: The conversation's working directory.
        scope: Either "conversation" or "project".

    Returns:
        The artifact directory path as a string.

    Raises:
        ValueError: If scope is invalid or conversation_id is missing for conversation scope.
    """
    if scope not in ("conversation", "project"):
        raise ValueError(f"Invalid scope: {scope}. Must be 'conversation' or 'project'.")

    base_path = Path(working_dir) / ".artifacts"

    if scope == "conversation":
        if conversation_id is None:
            raise ValueError("conversation_id is required for conversation scope")
        return str(base_path / "conversations" / str(conversation_id))
    else:  # scope == "project"
        return str(base_path / "project")
