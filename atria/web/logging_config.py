"""Logging configuration for web server."""

import logging
import sys

# Create a custom logger for Atria web
logger = logging.getLogger("atria.web")
logger.setLevel(logging.DEBUG)

# Create console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.DEBUG)

# Create formatter
formatter = logging.Formatter(
    "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
)
console_handler.setFormatter(formatter)

# Add handler to logger
if not logger.handlers:
    logger.addHandler(console_handler)

# Don't propagate to root logger (which is suppressed)
logger.propagate = False


def suppress_console_output(log_file: str | None = None):
    """Suppress web logger console output (for bridge mode).

    Called from the TUI runner before starting the embedded web server so that
    web-server log output doesn't leak into the TUI chat box via ConsoleBridge.

    Args:
        log_file: Optional path to redirect logs to a file instead of discarding them.
    """
    logger.handlers.clear()
    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    else:
        logger.addHandler(logging.NullHandler())
