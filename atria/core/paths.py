"""Centralized path management for Atria.

This module provides a single source of truth for all path-related constants
and helper functions. All paths in the application should be accessed through
this module rather than hardcoded strings.

Example:
    from atria.core.paths import get_paths

    paths = get_paths()
    settings_file = paths.global_settings
    sessions_dir = paths.global_sessions_dir

    # Or with a specific working directory
    paths = get_paths(working_dir=Path.cwd())
    project_settings = paths.project_settings
"""

from __future__ import annotations

import logging
import os
from functools import cached_property
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Directory and file names
APP_DIR_NAME = ".atria"
MCP_CONFIG_NAME = "mcp.json"
MCP_PROJECT_CONFIG_NAME = ".mcp.json"  # Project-level uses dot prefix at root
SESSIONS_DIR_NAME = "sessions"
PROJECTS_DIR_NAME = "projects"
FALLBACK_PROJECT_DIR_NAME = "-unknown-"
PLANS_DIR_NAME = "plans"
LOGS_DIR_NAME = "logs"
CACHE_DIR_NAME = "cache"
SKILLS_DIR_NAME = "skills"
AGENTS_DIR_NAME = "agents"
COMMANDS_DIR_NAME = "commands"
REPOS_DIR_NAME = "repos"
PLUGINS_DIR_NAME = "plugins"
MARKETPLACES_DIR_NAME = "marketplaces"
BUNDLES_DIR_NAME = "bundles"
PLUGIN_CACHE_DIR_NAME = "cache"
KNOWN_MARKETPLACES_FILE_NAME = "known_marketplaces.json"
INSTALLED_PLUGINS_FILE_NAME = "installed_plugins.json"
BUNDLES_FILE_NAME = "bundles.json"
SETTINGS_FILE_NAME = "settings.json"
SESSIONS_INDEX_FILE_NAME = "sessions-index.json"
AGENTS_FILE_NAME = "agents.json"
CONTEXT_FILE_NAME = "ATRIA.md"
HISTORY_FILE_NAME = "history.txt"

# Environment variable names for overrides
ENV_ATRIA_DIR = "ATRIA_DIR"
ENV_ATRIA_SESSION_DIR = "ATRIA_SESSION_DIR"
ENV_ATRIA_LOG_DIR = "ATRIA_LOG_DIR"
ENV_ATRIA_CACHE_DIR = "ATRIA_CACHE_DIR"


# ============================================================================
# Helpers
# ============================================================================


def encode_project_path(path: Path) -> str:
    """Encode an absolute path into a directory-safe string.

    Replaces ``/`` with ``-`` so the result can be used as a single directory name.
    Mirrors the convention used by Claude Code (e.g. ``/Users/foo/bar`` becomes
    ``-Users-foo-bar``).

    Args:
        path: Absolute filesystem path to encode.

    Returns:
        Encoded string suitable for use as a directory name.
    """
    resolved = str(path.resolve())
    return resolved.replace("/", "-")


# ============================================================================
# Paths Class
# ============================================================================


class Paths:
    """Centralized path management.

    Provides access to all application paths with support for:
    - Global paths (~/.atria/...)
    - Project paths (<working_dir>/.atria/...)
    - Environment variable overrides
    - Lazy directory creation

    Usage:
        paths = Paths()  # Uses Path.home() for global, Path.cwd() for project
        paths = Paths(working_dir=some_path)  # Specific project directory
    """

    def __init__(self, working_dir: Optional[Path] = None):
        """Initialize paths manager.

        Args:
            working_dir: Working directory for project-level paths.
                        Defaults to current working directory.
        """
        self._working_dir = working_dir or Path.cwd()

    @property
    def working_dir(self) -> Path:
        """Get the working directory."""
        return self._working_dir

    # ========================================================================
    # Global Paths (User-level, in ~/.atria/)
    # ========================================================================

    @cached_property
    def global_dir(self) -> Path:
        """Get the global atria directory.

        Can be overridden with ATRIA_DIR environment variable.
        Default: ~/.atria/

        On first access, migrates legacy ~/.opendev/ to ~/.atria/ if present
        and the new path does not yet exist.
        """
        env_override = os.environ.get(ENV_ATRIA_DIR)
        if env_override:
            return Path(env_override)
        target = Path.home() / APP_DIR_NAME
        legacy = Path.home() / ".opendev"
        if not target.exists() and legacy.exists() and legacy.is_dir():
            try:
                legacy.rename(target)
            except OSError as exc:
                # Cross-device rename, permissions, etc. — keep going with the
                # new path so the app can still start; data stays in legacy.
                logger.warning("failed to migrate %s -> %s: %s", legacy, target, exc)
        return target

    @cached_property
    def global_settings(self) -> Path:
        """Get global settings file path.

        Default: ~/.atria/settings.json
        """
        return self.global_dir / SETTINGS_FILE_NAME

    @cached_property
    def global_sessions_dir(self) -> Path:
        """Get global sessions directory.

        Can be overridden with ATRIA_SESSION_DIR environment variable.
        Default: ~/.atria/sessions/
        """
        env_override = os.environ.get(ENV_ATRIA_SESSION_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / SESSIONS_DIR_NAME

    @cached_property
    def global_projects_dir(self) -> Path:
        """Get global projects directory for project-scoped sessions.

        Default: ~/.atria/projects/
        """
        return self.global_dir / PROJECTS_DIR_NAME

    def project_sessions_dir(self, working_dir: Path) -> Path:
        """Get the project-scoped sessions directory for a given working directory.

        Args:
            working_dir: The project working directory.

        Returns:
            Path like ``~/.atria/projects/-Users-foo-bar/``
        """
        encoded = encode_project_path(working_dir)
        return self.global_projects_dir / encoded

    @cached_property
    def global_logs_dir(self) -> Path:
        """Get global logs directory.

        Can be overridden with ATRIA_LOG_DIR environment variable.
        Default: ~/.atria/logs/
        """
        env_override = os.environ.get(ENV_ATRIA_LOG_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / LOGS_DIR_NAME

    @cached_property
    def global_cache_dir(self) -> Path:
        """Get global cache directory.

        Can be overridden with ATRIA_CACHE_DIR environment variable.
        Default: ~/.atria/cache/
        """
        env_override = os.environ.get(ENV_ATRIA_CACHE_DIR)
        if env_override:
            return Path(env_override)
        return self.global_dir / CACHE_DIR_NAME

    @cached_property
    def global_skills_dir(self) -> Path:
        """Get global skills directory.

        Default: ~/.atria/skills/
        """
        return self.global_dir / SKILLS_DIR_NAME

    @cached_property
    def global_agents_dir(self) -> Path:
        """Get global agents directory.

        Default: ~/.atria/agents/
        """
        return self.global_dir / AGENTS_DIR_NAME

    @cached_property
    def global_agents_file(self) -> Path:
        """Get global agents.json file path.

        Default: ~/.atria/agents.json
        """
        return self.global_dir / AGENTS_FILE_NAME

    @cached_property
    def global_context_file(self) -> Path:
        """Get global context file (ATRIA.md) path.

        Default: ~/.atria/ATRIA.md
        """
        return self.global_dir / CONTEXT_FILE_NAME

    @cached_property
    def global_mcp_config(self) -> Path:
        """Get global MCP configuration file path.

        Default: ~/.atria/mcp.json
        """
        return self.global_dir / MCP_CONFIG_NAME

    @cached_property
    def global_plans_dir(self) -> Path:
        """Get global plans directory.

        Default: ~/.atria/plans/
        """
        return self.global_dir / PLANS_DIR_NAME

    @cached_property
    def global_repos_dir(self) -> Path:
        """Get global repos directory for cloned repositories.

        Default: ~/.atria/repos/
        """
        return self.global_dir / REPOS_DIR_NAME

    @cached_property
    def global_history_file(self) -> Path:
        """Get global command history file path.

        Default: ~/.atria/history.txt
        """
        return self.global_dir / HISTORY_FILE_NAME

    # ========================================================================
    # Plugin Paths (User-level, in ~/.atria/plugins/)
    # ========================================================================

    @cached_property
    def global_plugins_dir(self) -> Path:
        """Get global plugins directory.

        Default: ~/.atria/plugins/
        """
        return self.global_dir / PLUGINS_DIR_NAME

    @cached_property
    def global_marketplaces_dir(self) -> Path:
        """Get global marketplaces directory where marketplace repos are cloned.

        Default: ~/.atria/plugins/marketplaces/
        """
        return self.global_plugins_dir / MARKETPLACES_DIR_NAME

    @cached_property
    def global_plugin_cache_dir(self) -> Path:
        """Get global plugin cache directory for installed plugins.

        Default: ~/.atria/plugins/cache/
        """
        return self.global_plugins_dir / PLUGIN_CACHE_DIR_NAME

    @cached_property
    def known_marketplaces_file(self) -> Path:
        """Get known marketplaces registry file.

        Default: ~/.atria/plugins/known_marketplaces.json
        """
        return self.global_plugins_dir / KNOWN_MARKETPLACES_FILE_NAME

    @cached_property
    def global_installed_plugins_file(self) -> Path:
        """Get global installed plugins registry file.

        Default: ~/.atria/plugins/installed_plugins.json
        """
        return self.global_plugins_dir / INSTALLED_PLUGINS_FILE_NAME

    @cached_property
    def global_bundles_dir(self) -> Path:
        """Get global bundles directory for directly-installed plugin bundles.

        Default: ~/.atria/plugins/bundles/
        """
        return self.global_plugins_dir / BUNDLES_DIR_NAME

    @cached_property
    def global_bundles_file(self) -> Path:
        """Get global bundles registry file.

        Default: ~/.atria/plugins/bundles.json
        """
        return self.global_plugins_dir / BUNDLES_FILE_NAME

    # ========================================================================
    # Project Paths (Project-level, in <working_dir>/.atria/)
    # ========================================================================

    @cached_property
    def project_dir(self) -> Path:
        """Get project-level atria directory.

        Default: <working_dir>/.atria/
        """
        return self._working_dir / APP_DIR_NAME

    @cached_property
    def project_settings(self) -> Path:
        """Get project settings file path.

        Default: <working_dir>/.atria/settings.json
        """
        return self.project_dir / SETTINGS_FILE_NAME

    @cached_property
    def project_skills_dir(self) -> Path:
        """Get project skills directory.

        Default: <working_dir>/.atria/skills/
        """
        return self.project_dir / SKILLS_DIR_NAME

    @cached_property
    def project_agents_dir(self) -> Path:
        """Get project agents directory.

        Default: <working_dir>/.atria/agents/
        """
        return self.project_dir / AGENTS_DIR_NAME

    @cached_property
    def project_agents_file(self) -> Path:
        """Get project agents.json file path.

        Default: <working_dir>/.atria/agents.json
        """
        return self.project_dir / AGENTS_FILE_NAME

    @cached_property
    def project_commands_dir(self) -> Path:
        """Get project commands directory.

        Default: <working_dir>/.atria/commands/
        """
        return self.project_dir / COMMANDS_DIR_NAME

    @cached_property
    def project_context_file(self) -> Path:
        """Get project context file (ATRIA.md) path.

        Default: <working_dir>/ATRIA.md (at project root, not in .atria)
        """
        return self._working_dir / CONTEXT_FILE_NAME

    @cached_property
    def project_mcp_config(self) -> Path:
        """Get project MCP configuration file path.

        Note: Project MCP config uses .mcp.json at project root (not in .atria/)
        Default: <working_dir>/.mcp.json
        """
        return self._working_dir / MCP_PROJECT_CONFIG_NAME

    @cached_property
    def project_plugins_dir(self) -> Path:
        """Get project plugins directory.

        Default: <working_dir>/.atria/plugins/
        """
        return self.project_dir / PLUGINS_DIR_NAME

    @cached_property
    def project_installed_plugins_file(self) -> Path:
        """Get project installed plugins registry file.

        Default: <working_dir>/.atria/plugins/installed_plugins.json
        """
        return self.project_plugins_dir / INSTALLED_PLUGINS_FILE_NAME

    @cached_property
    def project_bundles_dir(self) -> Path:
        """Get project bundles directory for directly-installed plugin bundles.

        Default: <working_dir>/.atria/plugins/bundles/
        """
        return self.project_plugins_dir / BUNDLES_DIR_NAME

    @cached_property
    def project_bundles_file(self) -> Path:
        """Get project bundles registry file.

        Default: <working_dir>/.atria/plugins/bundles.json
        """
        return self.project_plugins_dir / BUNDLES_FILE_NAME

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def ensure_global_dirs(self) -> None:
        """Create all required global directories.

        Creates:
        - ~/.atria/
        - ~/.atria/sessions/
        - ~/.atria/logs/
        - ~/.atria/cache/
        - ~/.atria/skills/
        - ~/.atria/agents/
        - ~/.atria/plugins/
        - ~/.atria/plugins/marketplaces/
        - ~/.atria/plugins/cache/
        - ~/.atria/plugins/bundles/
        """
        self.global_dir.mkdir(parents=True, exist_ok=True)
        self.global_sessions_dir.mkdir(parents=True, exist_ok=True)
        self.global_projects_dir.mkdir(parents=True, exist_ok=True)
        self.global_logs_dir.mkdir(parents=True, exist_ok=True)
        self.global_cache_dir.mkdir(parents=True, exist_ok=True)
        self.global_plans_dir.mkdir(parents=True, exist_ok=True)
        self.global_skills_dir.mkdir(parents=True, exist_ok=True)
        self.global_agents_dir.mkdir(parents=True, exist_ok=True)
        self.global_plugins_dir.mkdir(parents=True, exist_ok=True)
        self.global_marketplaces_dir.mkdir(parents=True, exist_ok=True)
        self.global_plugin_cache_dir.mkdir(parents=True, exist_ok=True)
        self.global_bundles_dir.mkdir(parents=True, exist_ok=True)

    def ensure_project_dirs(self) -> None:
        """Create project directories if in a git repository.

        Only creates directories if .git exists in working directory.
        Creates:
        - <working_dir>/.atria/commands/ (if .git exists)
        """
        if (self._working_dir / ".git").exists():
            self.project_commands_dir.mkdir(parents=True, exist_ok=True)

    def get_skill_dirs(self) -> list[Path]:
        """Get all skill directories in priority order.

        Returns directories in order:
        1. Project skills (.atria/skills/) - highest priority
        2. User global skills (~/.atria/skills/)
        3. Project bundle skills (.atria/plugins/bundles/*/skills/)
        4. User bundle skills (~/.atria/plugins/bundles/*/skills/)
        5. Built-in skills (shipped with package) - lowest priority

        Only returns directories that exist.

        Returns:
            List of existing skill directories
        """
        dirs = []
        # Project skills (highest priority)
        if self.project_skills_dir.exists():
            dirs.append(self.project_skills_dir)
        # User global skills
        if self.global_skills_dir.exists():
            dirs.append(self.global_skills_dir)
        # Bundle skills are handled separately by PluginManager.get_plugin_skills()
        # to allow for proper source attribution
        return dirs

    def get_agents_dirs(self) -> list[Path]:
        """Get all agents directories in priority order.

        Returns directories in order: project first (highest priority), then global.
        Only returns directories that exist.

        Returns:
            List of existing agents directories
        """
        dirs = []
        if self.project_agents_dir.exists():
            dirs.append(self.project_agents_dir)
        if self.global_agents_dir.exists():
            dirs.append(self.global_agents_dir)
        return dirs

    def session_file(self, session_id: str) -> Path:
        """Get path to a specific session file.

        Args:
            session_id: Session ID

        Returns:
            Path to session JSON file
        """
        return self.global_sessions_dir / f"{session_id}.json"


# ============================================================================
# Singleton Access
# ============================================================================

_paths: Optional[Paths] = None


def get_paths(working_dir: Optional[Path] = None) -> Paths:
    """Get the global Paths instance.

    Creates a singleton instance on first call. If working_dir is provided,
    creates a new instance with that working directory.

    Args:
        working_dir: Optional working directory. If provided, creates a new
                    Paths instance with this directory (not cached as singleton).

    Returns:
        Paths instance
    """
    global _paths

    if working_dir is not None:
        # Return a new instance for specific working directory
        return Paths(working_dir)

    if _paths is None:
        _paths = Paths()

    return _paths


def set_paths(paths: Optional[Paths]) -> None:
    """Set the global Paths instance.

    Useful for testing or when needing to reset the singleton.

    Args:
        paths: Paths instance to set as global, or None to reset
    """
    global _paths
    _paths = paths


def reset_paths() -> None:
    """Reset the global Paths instance.

    Forces recreation on next get_paths() call.
    """
    global _paths
    _paths = None
