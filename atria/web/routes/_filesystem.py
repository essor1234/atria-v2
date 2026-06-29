"""Filesystem helper endpoints: path verification, directory browsing, file listing."""

import os
from pathlib import Path
from typing import Dict, List, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atria.web.state import get_state

router = APIRouter()


@router.post("/verify-path")
async def verify_path(path_data: Dict[str, str]) -> Dict[str, Any]:
    """Verify if a directory path exists and is accessible.

    Args:
        path_data: Dictionary with 'path' key

    Returns:
        Dictionary with exists, is_directory, and error fields

    Raises:
        HTTPException: If verification fails
    """
    try:
        path = path_data.get("path", "").strip()

        if not path:
            return {"exists": False, "is_directory": False, "error": "Path cannot be empty"}

        path_obj = Path(path).expanduser().resolve()

        if not path_obj.exists():
            return {"exists": False, "is_directory": False, "error": "Path does not exist"}

        if not path_obj.is_dir():
            return {"exists": True, "is_directory": False, "error": "Path is not a directory"}

        # Check if we have read access
        if not os.access(path_obj, os.R_OK):
            return {"exists": True, "is_directory": True, "error": "No read access to directory"}

        return {"exists": True, "is_directory": True, "path": str(path_obj), "error": None}

    except Exception as e:
        return {"exists": False, "is_directory": False, "error": f"Failed to verify path: {str(e)}"}


class BrowseDirectoryRequest(BaseModel):
    """Request model for browsing directories."""

    path: str = ""
    show_hidden: bool = False


@router.post("/browse-directory")
async def browse_directory(request: BrowseDirectoryRequest) -> Dict[str, Any]:
    """Browse directories at a given path for the workspace picker.

    Args:
        request: Request with path (defaults to home dir) and show_hidden flag

    Returns:
        Dictionary with current_path, parent_path, directories list, and error
    """
    try:
        raw = request.path.strip()
        if not raw:
            target = Path.home()
        else:
            target = Path(raw).expanduser().resolve()

        if not target.exists():
            return {
                "current_path": str(target),
                "parent_path": str(target.parent) if target.parent != target else None,
                "directories": [],
                "error": "Path does not exist",
            }

        if not target.is_dir():
            return {
                "current_path": str(target),
                "parent_path": str(target.parent) if target.parent != target else None,
                "directories": [],
                "error": "Path is not a directory",
            }

        if not os.access(target, os.R_OK):
            return {
                "current_path": str(target),
                "parent_path": str(target.parent) if target.parent != target else None,
                "directories": [],
                "error": "No read access to directory",
            }

        parent = target.parent
        parent_path = str(parent) if parent != target else None

        dirs = []
        try:
            for entry in target.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name.startswith(".") and not request.show_hidden:
                    continue
                if not os.access(entry, os.R_OK):
                    continue
                dirs.append({"name": entry.name, "path": str(entry)})
        except PermissionError:
            return {
                "current_path": str(target),
                "parent_path": parent_path,
                "directories": [],
                "error": "Permission denied reading directory contents",
            }

        dirs.sort(key=lambda d: d["name"].lower())

        return {
            "current_path": str(target),
            "parent_path": parent_path,
            "directories": dirs,
            "error": None,
        }

    except Exception as e:
        return {
            "current_path": request.path,
            "parent_path": None,
            "directories": [],
            "error": f"Failed to browse directory: {str(e)}",
        }


@router.get("/files")
async def list_files(query: str = "") -> Dict[str, Any]:
    """List files in the current session's working directory.

    Args:
        query: Optional search query to filter files

    Returns:
        Dictionary with files array

    Raises:
        HTTPException: If listing fails
    """
    try:
        state = get_state()
        session = await state.session_manager.get_current_session()

        if not session or not session.working_directory:
            return {"files": []}

        working_dir = Path(session.working_directory)
        if not working_dir.exists() or not working_dir.is_dir():
            return {"files": []}

        # Fallback ignore patterns if no .gitignore exists
        # Tier 1: Always exclude (obviously generated, never source code)
        always_exclude = {
            # Version Control
            ".git",
            ".hg",
            ".svn",
            ".bzr",
            "_darcs",
            ".fossil",
            # OS Generated
            ".DS_Store",
            ".Spotlight-V100",
            ".Trashes",
            "Thumbs.db",
            "desktop.ini",
            "$RECYCLE.BIN",
            # Python
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".pytype",
            ".pyre",
            ".hypothesis",
            ".tox",
            ".nox",
            "cython_debug",
            ".eggs",
            # Node/JS
            "node_modules",
            ".npm",
            ".yarn",
            ".pnpm-store",
            ".next",
            ".nuxt",
            ".output",
            ".svelte-kit",
            ".angular",
            ".parcel-cache",
            ".turbo",
            # IDE/Editor
            ".idea",
            ".vscode",
            ".vs",
            ".settings",
            # Java/Kotlin
            ".gradle",
            # Elixir
            "_build",
            "deps",
            ".elixir_ls",
            # iOS
            "Pods",
            "DerivedData",
            "xcuserdata",
            # Ruby
            ".bundle",
            # Virtual Environments
            ".venv",
            "venv",
            # Misc caches
            ".cache",
            ".sass-cache",
            ".eslintcache",
            ".tmp",
            ".temp",
            "tmp",
            "temp",
        }
        # Tier 2: Likely exclude (common build output dirs)
        likely_exclude = {
            "dist",
            "build",
            "out",
            "bin",
            "obj",
            "target",
            "coverage",
            "htmlcov",
            "cover",
            "logs",
            "vendor",
            "packages",
            "bower_components",
        }
        fallback_ignore_patterns = always_exclude | likely_exclude

        # Try to load gitignore parser
        gitignore_parser = None
        gitignore_path = working_dir / ".gitignore"
        if gitignore_path.exists():
            from atria.ui_textual.autocomplete_internal.gitignore import GitIgnoreParser

            gitignore_parser = GitIgnoreParser(working_dir)

        def should_skip_dir(dir_path: Path, dir_name: str) -> bool:
            """Check if a directory should be skipped."""
            if gitignore_parser:
                return gitignore_parser.should_skip_dir(dir_path)
            return dir_name in fallback_ignore_patterns

        def should_skip_file(file_path: Path) -> bool:
            """Check if a file should be skipped."""
            if gitignore_parser:
                return gitignore_parser.is_ignored(file_path)
            return False

        files = []
        try:
            # Use os.walk for more efficient traversal with pruning
            for root, dirs, filenames in os.walk(working_dir):
                root_path = Path(root)

                # Modify dirs in-place to skip ignored directories
                dirs[:] = [d for d in dirs if not should_skip_dir(root_path / d, d)]

                for filename in filenames:
                    file_path = root_path / filename

                    # Skip ignored files
                    if should_skip_file(file_path):
                        continue

                    # Get relative path
                    try:
                        rel_path = file_path.relative_to(working_dir)
                        path_str = str(rel_path)

                        # Filter by query if provided
                        if query and query.lower() not in path_str.lower():
                            continue

                        files.append({"path": path_str, "name": filename, "is_file": True})
                    except ValueError:
                        continue

                    # Limit early if we have enough results
                    if len(files) >= 100:
                        break

                if len(files) >= 100:
                    break

        except PermissionError:
            pass  # Skip directories we can't access

        # Sort files by path
        files.sort(key=lambda x: x["path"])

        # Limit to 100 results for performance
        files = files[:100]

        return {"files": files}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")
