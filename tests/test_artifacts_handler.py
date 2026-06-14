"""Unit tests for ArtifactsToolHandler."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import base64
from datetime import datetime

from atria.core.context_engineering.tools.handlers.artifacts_handler import ArtifactsToolHandler
from atria.core.context_engineering.tools.context import ToolExecutionContext


def create_mock_context(tmp_path):
    """Helper to create a mock context for testing."""
    mock_session = MagicMock()
    mock_session.metadata = {"conversation_id": 1, "project_id": 10}
    mock_session.working_directory = str(tmp_path)

    mock_session_manager = MagicMock()
    mock_session_manager.get_current_session = AsyncMock(return_value=mock_session)
    mock_session_manager._sessionmaker = MagicMock()

    mock_context = MagicMock(spec=ToolExecutionContext)
    mock_context.session_manager = mock_session_manager
    return mock_context


class TestArtifactsToolHandlerListImages:
    """Test suite for list_artifact_images functionality."""

    @pytest.fixture
    def handler(self, tmp_path):
        """Create an ArtifactsToolHandler."""
        return ArtifactsToolHandler()

    def test_list_artifact_images_conversation_scope(self, handler, tmp_path):
        """Test listing artifacts by conversation scope."""
        artifacts = [
            {
                "id": 1,
                "title": "screenshot.png",
                "type": "image",
                "size": 5000,
                "scope": "conversation",
                "created_at": datetime(2024, 1, 1, 12, 0, 0),
                "local_path": "artifacts/screenshot.png",
                "is_deleted": False,
            },
            {
                "id": 2,
                "title": "diagram.svg",
                "type": "image",
                "size": 2000,
                "scope": "conversation",
                "created_at": datetime(2024, 1, 2, 12, 0, 0),
                "local_path": "artifacts/diagram.svg",
                "is_deleted": False,
            },
        ]

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifacts
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifacts,  # artifacts list
                ]

                result = handler.list_artifact_images({"scope": "conversation"}, mock_context)

        assert result["success"] is True
        assert len(result["artifacts"]) == 2
        assert result["artifacts"][0]["id"] == 1
        assert result["artifacts"][0]["filename"] == "screenshot.png"
        assert result["artifacts"][1]["filename"] == "diagram.svg"

    def test_list_artifact_images_project_scope(self, handler, tmp_path):
        """Test listing artifacts by project scope."""
        artifacts = [
            {
                "id": 3,
                "title": "project_image.jpg",
                "type": "image",
                "size": 10000,
                "scope": "project",
                "created_at": datetime(2024, 1, 3, 12, 0, 0),
                "local_path": "artifacts/project_image.jpg",
                "is_deleted": False,
            },
        ]

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifacts
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifacts,  # artifacts list
                ]

                result = handler.list_artifact_images({"scope": "project"}, mock_context)

        assert result["success"] is True
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["id"] == 3
        assert result["artifacts"][0]["filename"] == "project_image.jpg"

    def test_list_artifact_images_empty_result(self, handler, tmp_path):
        """Test listing artifacts when none exist."""
        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and empty artifacts list
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    [],  # empty artifacts list
                ]

                result = handler.list_artifact_images({"scope": "conversation"}, mock_context)

        assert result["success"] is True
        assert len(result["artifacts"]) == 0


class TestArtifactsToolHandlerReadImage:
    """Test suite for read_artifact_image functionality."""

    @pytest.fixture
    def handler(self, tmp_path):
        """Create an ArtifactsToolHandler."""
        return ArtifactsToolHandler()

    def test_read_artifact_image_png_success(self, handler, tmp_path):
        """Test reading a PNG image artifact."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"fake_png_data" * 100
        image_path = tmp_path / "test_image.png"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 1,
            "title": "test_image.png",
            "type": "image",
            "local_path": "test_image.png",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        assert result["success"] is True
        assert result["mime_type"] == "image/png"
        assert "data:image/png;base64," in result["content"]
        b64_content = result["content"].replace("data:image/png;base64,", "")
        decoded = base64.b64decode(b64_content)
        assert decoded == image_data

    def test_read_artifact_image_jpeg_success(self, handler, tmp_path):
        """Test reading a JPEG image artifact."""
        image_data = b"\xff\xd8\xff" + b"fake_jpeg_data" * 100
        image_path = tmp_path / "test.jpg"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 2,
            "title": "test.jpg",
            "type": "image",
            "local_path": "test.jpg",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 2}, mock_context)

        assert result["success"] is True
        assert result["mime_type"] == "image/jpeg"
        assert "data:image/jpeg;base64," in result["content"]

    def test_read_artifact_image_svg_success(self, handler, tmp_path):
        """Test reading an SVG image artifact."""
        image_data = b"<svg></svg>"
        image_path = tmp_path / "test.svg"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 3,
            "title": "test.svg",
            "type": "image",
            "local_path": "test.svg",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 3}, mock_context)

        assert result["success"] is True
        assert result["mime_type"] == "image/svg+xml"

    def test_read_artifact_image_gif_success(self, handler, tmp_path):
        """Test reading a GIF image artifact."""
        image_data = b"GIF89a" + b"fake_gif_data" * 100
        image_path = tmp_path / "test.gif"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 4,
            "title": "test.gif",
            "type": "image",
            "local_path": "test.gif",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 4}, mock_context)

        assert result["success"] is True
        assert result["mime_type"] == "image/gif"

    def test_read_artifact_image_webp_success(self, handler, tmp_path):
        """Test reading a WebP image artifact."""
        image_data = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"fake_webp_data" * 100
        image_path = tmp_path / "test.webp"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 5,
            "title": "test.webp",
            "type": "image",
            "local_path": "test.webp",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 5}, mock_context)

        assert result["success"] is True
        assert result["mime_type"] == "image/webp"

    def test_read_artifact_image_deleted_artifact(self, handler, tmp_path):
        """Test reading a deleted artifact returns error."""
        artifact = {
            "id": 1,
            "title": "deleted.png",
            "type": "image",
            "local_path": "deleted.png",
            "is_deleted": True,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        assert result["success"] is False
        assert "deleted" in result["error"].lower()

    def test_read_artifact_image_not_found(self, handler, tmp_path):
        """Test reading a non-existent artifact."""
        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and None artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    None,  # artifact not found
                ]

                result = handler.read_artifact_image({"artifact_id": 999}, mock_context)

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_read_artifact_image_file_not_found(self, handler, tmp_path):
        """Test reading artifact when file doesn't exist on disk."""
        artifact = {
            "id": 1,
            "title": "missing.png",
            "type": "image",
            "local_path": "missing.png",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        assert result["success"] is False
        assert "not found" in result["error"].lower() or "cannot access" in result["error"].lower()

    def test_read_artifact_image_unsupported_type(self, handler, tmp_path):
        """Test reading an unsupported file type."""
        file_data = b"This is a text file"
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(file_data)

        artifact = {
            "id": 1,
            "title": "test.txt",
            "type": "file",
            "local_path": "test.txt",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        assert result["success"] is False
        assert "unsupported" in result["error"].lower() or "not an image" in result["error"].lower()

    def test_read_artifact_image_large_file(self, handler, tmp_path):
        """Test reading a very large image file."""
        image_data = b"PNG_DATA" * (2 * 1024 * 1024)
        image_path = tmp_path / "large.png"
        image_path.write_bytes(image_data)

        artifact = {
            "id": 1,
            "title": "large.png",
            "type": "image",
            "local_path": "large.png",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        assert result["success"] is False
        assert "too large" in result["error"].lower() or "size" in result["error"].lower()

    def test_read_artifact_image_mime_types(self, handler, tmp_path):
        """Test correct MIME type mapping for all supported formats."""
        test_cases = [
            ("test.png", "image/png"),
            ("test.jpg", "image/jpeg"),
            ("test.jpeg", "image/jpeg"),
            ("test.gif", "image/gif"),
            ("test.webp", "image/webp"),
            ("test.svg", "image/svg+xml"),
        ]

        for filename, expected_mime in test_cases:
            file_path = tmp_path / filename
            file_path.write_bytes(b"fake_data" * 100)

            artifact = {
                "id": 1,
                "title": filename,
                "type": "image",
                "local_path": filename,
                "is_deleted": False,
            }

            mock_context = create_mock_context(tmp_path)

            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
            ) as mock_repo_class:
                with patch(
                    "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
                ) as mock_run_sync:
                    mock_repo_instance = MagicMock()
                    mock_repo_class.return_value = mock_repo_instance

                    # Set up run_sync to return mocked session and artifact
                    mock_run_sync.side_effect = [
                        mock_context.session_manager.get_current_session.return_value,  # session
                        artifact,  # artifact data
                    ]

                    result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

            assert result["success"] is True, f"Failed for {filename}"
            assert result["mime_type"] == expected_mime, f"Wrong MIME type for {filename}"

    def test_read_artifact_image_path_traversal_attack(self, handler, tmp_path):
        """Test that path traversal attacks are blocked."""
        # Create a file outside the working directory
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secret.png"
        outside_file.write_bytes(b"fake_png_data")

        # Try to access it via path traversal
        artifact = {
            "id": 1,
            "title": "secret.png",
            "type": "image",
            "local_path": "../outside/secret.png",
            "is_deleted": False,
        }

        mock_context = create_mock_context(tmp_path)

        with patch(
            "atria.core.context_engineering.tools.handlers.artifacts_handler.ArtifactRepository"
        ) as mock_repo_class:
            with patch(
                "atria.core.context_engineering.tools.handlers.artifacts_handler.run_sync"
            ) as mock_run_sync:
                mock_repo_instance = MagicMock()
                mock_repo_class.return_value = mock_repo_instance

                # Set up run_sync to return mocked session and artifact
                mock_run_sync.side_effect = [
                    mock_context.session_manager.get_current_session.return_value,  # session
                    artifact,  # artifact data
                ]

                result = handler.read_artifact_image({"artifact_id": 1}, mock_context)

        # Path traversal should be blocked
        assert result["success"] is False
        assert "Access denied" in result["error"] or "outside project directory" in result["error"]
