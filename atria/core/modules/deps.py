"""Install per-module Python dependencies into the active environment.

Each module may ship a ``requirements.txt``; on registry load we install it
into ``sys.executable``'s env (the shared Atria venv) and stamp the hash next
to it so unchanged manifests are skipped on subsequent loads.

There is intentionally no per-module ``.venv`` — modules share the host
interpreter, matching how Dockerfile pre-bakes deps at build time.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REQ_FILE = "requirements.txt"
STAMP_FILE = ".deps.sha256"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_pip() -> bool:
    """Make sure ``python -m pip`` is callable. Returns False if unavailable."""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        subprocess.check_call(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _install_cmd(req: Path) -> list[str]:
    """Prefer ``uv pip install`` (fast, no pip needed); fall back to pip."""
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip", "install", "--python", sys.executable, "-r", str(req)]
    return [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)]


def install_module_deps(module_dir: Path) -> bool:
    """Install ``module_dir/requirements.txt`` if present and changed.

    Returns True if an install ran (or wasn't needed because deps were already
    current), False on error. Errors are logged but never raised — a broken
    module shouldn't block the registry from loading the rest.
    """
    req = module_dir / REQ_FILE
    if not req.is_file():
        return True

    stamp = module_dir / STAMP_FILE
    current = _hash(req)
    previous = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    if current == previous:
        return True

    cmd = _install_cmd(req)
    if cmd[0].endswith(("python", "python3", "python.exe")) and not _ensure_pip():
        logger.warning(
            "module %s: pip unavailable in %s, skipping requirements.txt",
            module_dir.name,
            sys.executable,
        )
        return False

    logger.info("module %s: installing %s", module_dir.name, REQ_FILE)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        logger.warning("module %s: dep install failed (%s)", module_dir.name, exc)
        return False

    try:
        stamp.write_text(current, encoding="utf-8")
    except OSError as exc:
        logger.warning("module %s: could not write stamp: %s", module_dir.name, exc)
    return True
