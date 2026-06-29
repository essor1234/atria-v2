"""Resolve a friendly activity label from a bash command invoking a module script.

Used by the web tool broadcaster (Simple Mode) to turn
``python <modules>/warehouse/scripts/inventory.py receive …`` into
``ActivityLabel(running="Receiving stock…", done="Stock received")``.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Optional

from atria.core.modules.store import ActivityLabel, _read_manifest


def resolve_activity_label(command: str, modules_root: Path) -> Optional[ActivityLabel]:
    """Map a shell command to a module's friendly activity label.

    Returns ``None`` for non-module commands or modules without an ``activity``
    block, in which case the caller falls back to a generic label.

    Only absolute script paths under ``modules_root`` are recognized; relative
    paths are skipped (commands are broadcast with fully-resolved script paths).

    Args:
        command: The full shell command (may include flags and args).
        modules_root: Absolute path to the active modules directory.

    Returns:
        The matched ``ActivityLabel`` (action-specific, else the module default)
        or ``None``.
    """
    if not command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    root = modules_root.resolve()
    for i, token in enumerate(tokens):
        if not token.endswith(".py"):
            continue
        script = Path(token)
        if not script.is_absolute():
            continue
        try:
            rel = script.resolve().relative_to(root)
        except ValueError:
            continue
        if not rel.parts:
            continue
        manifest = _read_manifest(root / rel.parts[0])
        if manifest is None:
            return None

        subcommand: Optional[str] = None
        for nxt in tokens[i + 1 :]:
            if nxt.startswith("-"):
                continue
            subcommand = nxt
            break

        if subcommand and subcommand in manifest.activity_actions:
            return manifest.activity_actions[subcommand]
        return manifest.activity_default
    return None
