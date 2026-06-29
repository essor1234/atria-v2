"""Debug logging helpers shared by the ReactExecutor tool-processing mixins."""

from __future__ import annotations

import logging

_ctx_logger = logging.getLogger("swecli.context_debug")


def _debug_log(message: str) -> None:
    """Write debug message to /tmp/swecli_react_debug.log."""
    from datetime import datetime

    log_file = "/tmp/swecli_react_debug.log"
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def _session_debug():
    """Get the current session debug logger."""
    from atria.core.debug import get_debug_logger

    return get_debug_logger()
