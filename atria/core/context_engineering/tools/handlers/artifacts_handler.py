"""Handler for artifact-related tools (list and read artifact images)."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from atria.db.repositories.artifact_repo import ArtifactRepository
from atria.db.sync import run_sync

logger = logging.getLogger(__name__)


class ArtifactsToolHandler:
    """Handles artifact-related operations like listing and reading artifact images."""

    # MIME type mapping for supported image formats
    _MIME_TYPES = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }

    # Maximum file size: 10MB
    _MAX_FILE_SIZE = 10 * 1024 * 1024

    def __init__(self) -> None:
        """Initialize the artifacts handler."""

    def list_artifact_images(
        self,
        args: dict[str, Any],
        context: Any = None,
    ) -> dict[str, Any]:
        """List artifact images by scope (conversation, project, or both).

        Args:
            args: Arguments dict containing 'scope' (optional)
            context: ToolExecutionContext with session_manager

        Returns:
            Dict with success, artifacts list, and error message if applicable
        """
        try:
            scope = args.get("scope", "conversation")

            # Get session manager and project/conversation info
            session_manager = context.session_manager if context else None
            if not session_manager:
                return {
                    "success": False,
                    "error": "Session manager not available",
                    "artifacts": [],
                }

            # Get current session synchronously
            session = run_sync(session_manager.get_current_session())
            if not session:
                return {
                    "success": False,
                    "error": "No active session",
                    "artifacts": [],
                }

            conversation_id = session.metadata.get("conversation_id")
            project_id = session.metadata.get("project_id")

            if not conversation_id and not project_id:
                return {
                    "success": False,
                    "error": "No conversation_id or project_id in session metadata",
                    "artifacts": [],
                }

            # Get sessionmaker from session manager
            # Note: Using _sessionmaker (private API) to access SQLAlchemy sessionmaker.
            # This is necessary because SessionManager doesn't expose this functionality
            # publicly. A public method should be added to SessionManager if this becomes
            # a common pattern.
            sessionmaker = session_manager._sessionmaker

            # Create artifact repo and fetch artifacts
            artifact_repo = ArtifactRepository(sessionmaker)
            artifacts = []

            if scope == "conversation" and conversation_id:
                artifacts = run_sync(
                    artifact_repo.list_by_conversation_and_scope(conversation_id, scope)
                )
            elif scope == "project" and project_id:
                artifacts = run_sync(artifact_repo.list_by_project_and_scope(project_id, scope))
            elif scope == "both":
                # Fetch from both scopes and combine results
                if conversation_id:
                    conv_artifacts = run_sync(
                        artifact_repo.list_by_conversation_and_scope(
                            conversation_id, "conversation"
                        )
                    )
                    artifacts.extend(conv_artifacts)
                if project_id:
                    proj_artifacts = run_sync(
                        artifact_repo.list_by_project_and_scope(project_id, "project")
                    )
                    artifacts.extend(proj_artifacts)
            else:
                return {
                    "success": False,
                    "error": f"Invalid scope '{scope}' or missing context",
                    "artifacts": [],
                }

            # Transform database results into response format
            result_artifacts = []
            for artifact in artifacts:
                result_artifacts.append(
                    {
                        "id": artifact.get("id"),
                        "filename": artifact.get("title", ""),
                        "type": artifact.get("type", ""),
                        "size": artifact.get("size", 0),
                        "scope": artifact.get("scope", ""),
                        "created_at": artifact.get("created_at"),
                    }
                )

            return {
                "success": True,
                "artifacts": result_artifacts,
            }
        except Exception as exc:
            import traceback

            logger.error(f"Error listing artifact images: {exc}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": f"Failed to list artifacts: {str(exc)}",
                "artifacts": [],
            }

    def read_artifact_image(
        self,
        args: dict[str, Any],
        context: Any = None,
    ) -> dict[str, Any]:
        """Read artifact image file content as base64.

        Args:
            args: Arguments dict containing 'artifact_id'
            context: ToolExecutionContext with session_manager

        Returns:
            Dict with success, content (base64), mime_type, and error if applicable
        """
        try:
            artifact_id = args.get("artifact_id")
            if not artifact_id:
                return {
                    "success": False,
                    "error": "artifact_id is required",
                    "content": None,
                    "mime_type": None,
                }

            # Get session manager
            session_manager = context.session_manager if context else None
            if not session_manager:
                return {
                    "success": False,
                    "error": "Session manager not available",
                    "content": None,
                    "mime_type": None,
                }

            # Get current session synchronously
            session = run_sync(session_manager.get_current_session())
            if not session:
                return {
                    "success": False,
                    "error": "No active session",
                    "content": None,
                    "mime_type": None,
                }

            # Get working directory from session
            working_dir = session.working_directory
            if working_dir:
                working_dir = Path(working_dir)
            else:
                working_dir = Path.cwd()

            # Get sessionmaker from session manager
            # Note: Using _sessionmaker (private API) to access SQLAlchemy sessionmaker.
            # This is necessary because SessionManager doesn't expose this functionality
            # publicly. A public method should be added to SessionManager if this becomes
            # a common pattern.
            sessionmaker = session_manager._sessionmaker

            # Create artifact repo and get artifact
            artifact_repo = ArtifactRepository(sessionmaker)
            artifact = run_sync(artifact_repo.get_by_id(artifact_id))

            if artifact is None:
                return {
                    "success": False,
                    "error": f"Artifact {artifact_id} not found",
                    "content": None,
                    "mime_type": None,
                }

            # Check if deleted
            if artifact.get("is_deleted"):
                return {
                    "success": False,
                    "error": f"Artifact {artifact_id} has been deleted",
                    "content": None,
                    "mime_type": None,
                }

            # Get the local path
            local_path = artifact.get("local_path")
            if not local_path:
                return {
                    "success": False,
                    "error": f"Artifact {artifact_id} has no file path",
                    "content": None,
                    "mime_type": None,
                }

            # Construct full path
            full_path = working_dir / local_path

            # Validate path traversal: ensure resolved path stays within working_dir
            try:
                resolved_path = full_path.resolve()
                resolved_working_dir = working_dir.resolve()
                if not str(resolved_path).startswith(str(resolved_working_dir)):
                    return {
                        "success": False,
                        "error": "Access denied: path outside project directory",
                        "content": None,
                        "mime_type": None,
                    }
            except Exception as exc:
                return {
                    "success": False,
                    "error": f"Invalid path: {str(exc)}",
                    "content": None,
                    "mime_type": None,
                }

            # Check if file exists
            if not full_path.exists():
                return {
                    "success": False,
                    "error": f"Artifact file not found: {local_path}",
                    "content": None,
                    "mime_type": None,
                }

            # Get file extension
            suffix = full_path.suffix.lower()

            # Check if it's a supported image format
            if suffix not in self._MIME_TYPES:
                return {
                    "success": False,
                    "error": f"Unsupported file type '{suffix}'. Supported: {', '.join(self._MIME_TYPES.keys())}",
                    "content": None,
                    "mime_type": None,
                }

            # Read file
            try:
                file_data = full_path.read_bytes()
            except (OSError, IOError) as exc:
                return {
                    "success": False,
                    "error": f"Cannot access file: {str(exc)}",
                    "content": None,
                    "mime_type": None,
                }

            # Check file size
            if len(file_data) > self._MAX_FILE_SIZE:
                size_mb = len(file_data) / (1024 * 1024)
                return {
                    "success": False,
                    "error": f"File too large ({size_mb:.1f}MB). Maximum size is 10MB",
                    "content": None,
                    "mime_type": None,
                }

            # Encode to base64
            b64_content = base64.b64encode(file_data).decode("ascii")
            mime_type = self._MIME_TYPES[suffix]

            return {
                "success": True,
                "content": f"data:{mime_type};base64,{b64_content}",
                "mime_type": mime_type,
            }

        except Exception as exc:
            logger.error(f"Error reading artifact image: {exc}")
            return {
                "success": False,
                "error": f"Failed to read artifact: {str(exc)}",
                "content": None,
                "mime_type": None,
            }
