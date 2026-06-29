"""Command classification and output-truncation constants for the bash tool.

Kept separate from ``tool.py`` so the security mixin (and other callers) can
import them without pulling in the full ``BashTool`` module.
"""

from __future__ import annotations


# Safe commands that are generally allowed
SAFE_COMMANDS = [
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "echo",
    "pwd",
    "which",
    "whoami",
    "git",
    "pytest",
    "python",
    "python3",
    "pip",
    "node",
    "npm",
    "npx",
    "yarn",
    "docker",
    "kubectl",
    "make",
    "cmake",
]

# Dangerous patterns that should be blocked
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",  # Delete root
    r"sudo",  # Privileged execution
    r"chmod\s+-R\s+777",  # Permissive permissions
    r":\(\)\{\s*:\|\:&\s*\};:",  # Fork bomb
    r"mv\s+/",  # Move root directories
    r">\s*/dev/sd[a-z]",  # Write to disk directly
    r"dd\s+if=.*of=/dev",  # Disk operations
    r"curl.*\|\s*bash",  # Download and execute
    r"wget.*\|\s*bash",  # Download and execute
]

# Commands that commonly require y/n confirmation (safe scaffolding tools)
INTERACTIVE_COMMANDS = [
    r"\bnpx\b",  # npx create-*, npx degit, etc.
    r"\bnpm\s+(init|create)\b",  # npm init / npm create
    r"\byarn\s+create\b",  # yarn create
    r"\bng\s+new\b",  # Angular CLI
    r"\bvue\s+create\b",  # Vue CLI
    r"\bcreate-react-app\b",  # CRA
    r"\bnext\s+create\b",  # Next.js
    r"\bvite\s+create\b",  # Vite
    r"\bpnpm\s+create\b",  # pnpm create
]

# Timeout configuration for activity-based timeout
# Only timeout if command produces no output for IDLE_TIMEOUT seconds
IDLE_TIMEOUT = 60  # Timeout after 60 seconds of no output
MAX_TIMEOUT = 600  # Absolute max runtime: 10 minutes (safety cap)

# Output truncation
MAX_OUTPUT_CHARS = 30_000
KEEP_HEAD_CHARS = 10_000
KEEP_TAIL_CHARS = 10_000

# Metadata cap for LLM context (more compact than display truncation)
MAX_LLM_METADATA_CHARS = 15_000
LLM_KEEP_HEAD_CHARS = 5_000
LLM_KEEP_TAIL_CHARS = 5_000
