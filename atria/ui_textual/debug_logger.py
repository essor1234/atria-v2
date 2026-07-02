"""Debug logger that writes to a file for debugging Textual apps.

Textual captures stderr, so we need to write to a file directly.
"""

import tempfile
from datetime import datetime
from pathlib import Path

# Debug log file path. Use the OS temp dir so this works cross-platform;
# a hardcoded "/tmp/..." resolves to "<drive>:\tmp\..." on Windows and does
# not exist, which previously crashed the agent loop on every debug_log call.
DEBUG_LOG_PATH = Path(tempfile.gettempdir()) / "swecli-interrupt-debug.log"


def debug_log(component: str, message: str) -> None:
    """Write a debug message to the log file.

    Args:
        component: Name of the component (e.g., "ChatApp", "InterruptManager")
        message: The debug message
    """
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] [{component}] {message}\n"

    # Append to file. Debug logging must never break the caller, so swallow any
    # filesystem error (missing dir, permissions, etc.) silently.
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def clear_debug_log() -> None:
    """Clear the debug log file."""
    if DEBUG_LOG_PATH.exists():
        DEBUG_LOG_PATH.unlink()
    # Create empty file
    DEBUG_LOG_PATH.touch()
