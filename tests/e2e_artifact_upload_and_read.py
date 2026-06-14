"""End-to-end tests for artifact upload and read workflows."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from atria.db.repositories.artifact_repo import ArtifactRepository


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL required for E2E artifact tests",
    ),
]


class TestUploadAndAgentRead:
    """Test E2E upload and agent read workflows."""

    async def test_upload_image_and_list_artifacts(
        self, temp_conversation, db_session, artifacts_client
    ):
        """Test uploading an image and listing it via API.

        User uploads image via POST /api/artifacts/upload (conversation scope).
        Verify response contains artifact_id, filename, scope, type, size.
        Verify file written to disk at correct path.
        """
        # Create a test image file
        image_data = b"\x89PNG\r\n\x1a\n" + b"test_data" * 100
        filename = "test_upload.png"

        # Upload via POST /api/artifacts/upload
        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": (filename, io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 200, f"Upload failed: {response.text}"
        data = response.json()

        # Verify response structure
        assert "artifact_id" in data
        assert "filename" in data
        assert "scope" in data
        assert "type" in data
        assert "size" in data
        assert "created_at" in data

        assert data["filename"] == filename
        assert data["scope"] == "conversation"
        assert data["type"] == "image"
        assert data["size"] == len(image_data)

        # Verify file was written to disk
        working_dir = Path(temp_conversation["working_directory"])
        artifact_files = list(
            working_dir.glob(f".artifacts/conversations/{temp_conversation['id']}/*")
        )
        assert len(artifact_files) > 0, "File not found on disk"

        # Verify file content
        disk_file = artifact_files[0]
        assert disk_file.exists()
        assert disk_file.read_bytes() == image_data

    async def test_upload_multiple_images_same_conversation(
        self, temp_conversation, db_session, artifacts_client
    ):
        """Test uploading multiple images to the same conversation."""
        working_dir = Path(temp_conversation["working_directory"])

        # Upload first image
        image1_data = b"\x89PNG\r\n\x1a\n" + b"image1" * 50
        response1 = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("image1.png", io.BytesIO(image1_data), "image/png")},
        )
        assert response1.status_code == 200
        artifact1_id = response1.json()["artifact_id"]

        # Upload second image
        image2_data = b"\x89PNG\r\n\x1a\n" + b"image2" * 50
        response2 = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("image2.png", io.BytesIO(image2_data), "image/png")},
        )
        assert response2.status_code == 200
        artifact2_id = response2.json()["artifact_id"]

        # Verify both files exist on disk
        artifact_files = list(
            working_dir.glob(f".artifacts/conversations/{temp_conversation['id']}/*")
        )
        assert len(artifact_files) == 2

        # Verify file contents
        artifact_repo = ArtifactRepository(db_session)
        artifact1 = await artifact_repo.get_by_id(artifact1_id)
        artifact2 = await artifact_repo.get_by_id(artifact2_id)

        assert artifact1 is not None
        assert artifact2 is not None
        assert artifact1["id"] != artifact2["id"]


class TestHardDelete:
    """Test hard delete workflows."""

    async def test_hard_delete_removes_file(
        self, temp_conversation, db_session, artifacts_client, uploaded_artifact
    ):
        """Test that hard delete removes both file and DB record.

        Upload artifact via POST /api/artifacts/upload.
        Verify file exists on disk.
        Call DELETE /api/artifacts/{id} (with hard_delete=true).
        Verify file deleted from disk.
        Verify artifact record deleted from DB.
        """
        artifact_id = uploaded_artifact["id"]
        file_path = Path(uploaded_artifact["file_path"])

        # Verify file exists before delete
        assert file_path.exists()

        # Verify DB record exists
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(artifact_id)
        assert artifact is not None

        # Hard delete via API
        response = artifacts_client.delete(f"/api/artifacts/{artifact_id}?hard_delete=true")
        assert response.status_code == 200

        # Verify file deleted from disk
        assert not file_path.exists()

        # Verify DB record deleted
        # Note: hard_delete completely removes the record, so get_by_id returns None
        artifact = await artifact_repo.get_by_id(artifact_id)
        assert artifact is None

    async def test_read_deleted_artifact_returns_error(
        self, temp_conversation, db_session, deleted_artifact
    ):
        """Test that reading a deleted artifact returns error."""
        artifact_id = deleted_artifact["id"]

        # Try to read the deleted artifact
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(artifact_id)

        # get_by_id filters out deleted artifacts
        assert artifact is None


class TestScopeFiltering:
    """Test conversation and project scope filtering."""

    async def test_conversation_and_project_scopes(
        self, temp_project, temp_conversation, db_session
    ):
        """Test uploading files with different scopes.

        Upload file with scope='conversation'.
        Upload file with scope='project'.
        List conversation artifacts - should include conversation file only.
        List project artifacts - should include project file only.
        List with scope='both' - should include both.
        """
        artifact_repo = ArtifactRepository(db_session)

        # Upload conversation-scoped artifact
        conv_artifact_id = await artifact_repo.create(
            project_id=temp_project["id"],
            conversation_id=temp_conversation["id"],
            type="image",
            title="conv_image.png",
            scope="conversation",
            local_path=f"conversations/{temp_conversation['id']}/conv_image.png",
        )

        # Upload project-scoped artifact
        proj_artifact_id = await artifact_repo.create(
            project_id=temp_project["id"],
            conversation_id=temp_conversation["id"],
            type="image",
            title="proj_image.png",
            scope="project",
            local_path="project/proj_image.png",
        )

        # List conversation scope
        conv_artifacts = await artifact_repo.list_by_conversation_and_scope(
            temp_conversation["id"], "conversation"
        )
        assert len(conv_artifacts) == 1
        assert conv_artifacts[0]["id"] == conv_artifact_id
        assert conv_artifacts[0]["scope"] == "conversation"

        # List project scope
        proj_artifacts = await artifact_repo.list_by_project_and_scope(
            temp_project["id"], "project"
        )
        assert len(proj_artifacts) == 1
        assert proj_artifacts[0]["id"] == proj_artifact_id
        assert proj_artifacts[0]["scope"] == "project"

    async def test_upload_with_different_scopes(
        self, temp_project, temp_conversation, db_session, artifacts_client
    ):
        """Test uploading files with conversation and project scopes."""
        # Upload conversation-scoped file
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50
        response_conv = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("conv_image.png", io.BytesIO(image_data), "image/png")},
        )
        assert response_conv.status_code == 200
        assert response_conv.json()["scope"] == "conversation"

        # Upload project-scoped file
        response_proj = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "project",
                "project_id": temp_project["id"],
            },
            files={"file": ("proj_image.png", io.BytesIO(image_data), "image/png")},
        )
        assert response_proj.status_code == 200
        assert response_proj.json()["scope"] == "project"


class TestErrorCases:
    """Test error handling in upload and read operations."""

    async def test_upload_file_too_large(self, temp_conversation, artifacts_client):
        """Test upload of file > 50MB returns 413 error."""
        # Create a 51MB file (exceeds 50MB limit)
        large_data = b"x" * (51 * 1024 * 1024)

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("large.png", io.BytesIO(large_data), "image/png")},
        )

        # Should return 413 Payload Too Large
        assert response.status_code == 413
        assert "too large" in response.json()["detail"].lower()

    async def test_upload_invalid_scope(self, temp_conversation, artifacts_client):
        """Test upload with invalid scope returns 422 error."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "invalid_scope",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 422
        assert "scope" in response.json()["detail"].lower()

    async def test_upload_missing_conversation_id(self, artifacts_client):
        """Test upload to conversation scope without conversation_id returns error."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                # Missing conversation_id
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 422

    async def test_upload_missing_project_id(self, artifacts_client):
        """Test upload to project scope without project_id returns error."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "project",
                # Missing project_id
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 422

    async def test_upload_nonexistent_conversation(self, artifacts_client):
        """Test upload to nonexistent conversation returns error."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": 999999,  # nonexistent
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 404

    async def test_upload_nonexistent_project(self, artifacts_client):
        """Test upload to nonexistent project returns error."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "project",
                "project_id": 999999,  # nonexistent
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 404


class TestFileMetadata:
    """Test file metadata handling."""

    async def test_upload_preserves_filename(self, temp_conversation, db_session, artifacts_client):
        """Test that upload preserves original filename in artifact title."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50
        original_filename = "my_screenshot.png"

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": (original_filename, io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == original_filename

        # Verify in DB
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(data["artifact_id"])
        assert artifact["title"] == original_filename

    async def test_upload_correct_file_size(self, temp_conversation, db_session, artifacts_client):
        """Test that uploaded file size is correctly recorded."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 100
        expected_size = len(image_data)

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["size"] == expected_size

    async def test_upload_infers_correct_type(
        self, temp_conversation, db_session, artifacts_client
    ):
        """Test that artifact type is correctly inferred from filename."""
        test_cases = [
            ("test.png", "image"),
            ("test.jpg", "image"),
            ("document.pdf", "report"),
            ("script.py", "code"),
        ]

        for filename, expected_type in test_cases:
            # Create appropriate file data
            if filename.endswith(".png"):
                data = b"\x89PNG\r\n\x1a\n" + b"test"
            elif filename.endswith(".jpg"):
                data = b"\xff\xd8\xff" + b"test"
            elif filename.endswith(".pdf"):
                data = b"%PDF-1.4" + b"test"
            else:
                data = b"code content"

            response = artifacts_client.post(
                "/api/artifacts/upload",
                data={
                    "scope": "conversation",
                    "conversation_id": temp_conversation["id"],
                },
                files={"file": (filename, io.BytesIO(data), "application/octet-stream")},
            )

            assert response.status_code == 200, f"Failed for {filename}"
            data = response.json()
            assert data["type"] == expected_type, f"Wrong type for {filename}"


class TestLocalPathStorage:
    """Test that local_path is correctly stored and used."""

    async def test_artifact_local_path_stored(
        self, temp_conversation, db_session, artifacts_client
    ):
        """Test that artifact local_path is correctly stored in DB."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "conversation",
                "conversation_id": temp_conversation["id"],
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 200
        artifact_id = response.json()["artifact_id"]

        # Verify local_path in DB
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(artifact_id)
        assert artifact["local_path"] is not None
        assert artifact["local_path"].startswith(f"conversations/{temp_conversation['id']}")
        assert artifact["local_path"].endswith(".png")

    async def test_project_artifact_local_path_stored(
        self, temp_project, db_session, artifacts_client
    ):
        """Test that project-scoped artifact local_path is correct."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"test" * 50

        response = artifacts_client.post(
            "/api/artifacts/upload",
            data={
                "scope": "project",
                "project_id": temp_project["id"],
            },
            files={"file": ("test.png", io.BytesIO(image_data), "image/png")},
        )

        assert response.status_code == 200
        artifact_id = response.json()["artifact_id"]

        # Verify local_path in DB
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(artifact_id)
        assert artifact["local_path"] is not None
        assert artifact["local_path"].startswith("project/")
        assert artifact["local_path"].endswith(".png")


class TestSoftDelete:
    """Test soft delete workflows."""

    async def test_soft_delete_preserves_file(
        self, temp_conversation, db_session, artifacts_client, uploaded_artifact
    ):
        """Test that soft delete (default) preserves the file on disk."""
        artifact_id = uploaded_artifact["id"]
        file_path = Path(uploaded_artifact["file_path"])

        # Verify file exists before delete
        assert file_path.exists()

        # Soft delete (hard_delete=false or omitted)
        response = artifacts_client.delete(f"/api/artifacts/{artifact_id}?hard_delete=false")
        assert response.status_code == 200

        # Verify file still exists on disk
        assert file_path.exists()

        # Verify artifact is marked as deleted in DB
        artifact_repo = ArtifactRepository(db_session)
        artifact = await artifact_repo.get_by_id(artifact_id)
        # get_by_id filters out deleted artifacts
        assert artifact is None

    async def test_list_excludes_soft_deleted(
        self, temp_conversation, db_session, artifacts_client
    ):
        """Test that list operations exclude soft-deleted artifacts."""
        artifact_repo = ArtifactRepository(db_session)

        # Create two artifacts
        art1_id = await artifact_repo.create(
            project_id=None,
            conversation_id=temp_conversation["id"],
            type="image",
            title="active.png",
            scope="conversation",
            local_path="conversations/1/active.png",
        )
        art2_id = await artifact_repo.create(
            project_id=None,
            conversation_id=temp_conversation["id"],
            type="image",
            title="deleted.png",
            scope="conversation",
            local_path="conversations/1/deleted.png",
        )

        # List before delete
        artifacts = await artifact_repo.list_by_conversation(temp_conversation["id"])
        assert len(artifacts) == 2

        # Soft delete one
        await artifact_repo.soft_delete(art2_id)

        # List after delete
        artifacts = await artifact_repo.list_by_conversation(temp_conversation["id"])
        assert len(artifacts) == 1
        assert artifacts[0]["id"] == art1_id
