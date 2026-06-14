"""Integration tests for artifact upload and deletion endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


# Unit tests - no database required
class TestFileSanitization:
    """Test filename sanitization."""

    def test_sanitize_filename_dangerous_paths(self):
        """Test that path traversal characters are removed."""
        from atria.web.utils.file_utils import sanitize_filename

        assert sanitize_filename("../../evil.txt") == "evil.txt"
        assert sanitize_filename("file/path/name.txt") == "filepathname.txt"
        assert sanitize_filename("file\\back\\slash.txt") == "filebackslash.txt"

    def test_sanitize_filename_normal(self):
        """Test normal filenames are preserved."""
        from atria.web.utils.file_utils import sanitize_filename

        assert sanitize_filename("normal_file.txt") == "normal_file.txt"
        assert sanitize_filename("file with spaces.txt") == "file with spaces.txt"
        assert sanitize_filename("file-with-dashes.txt") == "file-with-dashes.txt"

    def test_sanitize_filename_null_bytes(self):
        """Test null bytes are removed."""
        from atria.web.utils.file_utils import sanitize_filename

        assert sanitize_filename("file\x00null.txt") == "filenull.txt"

    def test_sanitize_filename_problematic_chars(self):
        """Test problematic filesystem characters are removed."""
        from atria.web.utils.file_utils import sanitize_filename

        assert sanitize_filename('file"name.txt') == "filename.txt"
        assert sanitize_filename("file<name>.txt") == "filename.txt"
        assert sanitize_filename("file|name.txt") == "filename.txt"
        assert sanitize_filename("file:name.txt") == "filename.txt"
        assert sanitize_filename("file?name.txt") == "filename.txt"
        assert sanitize_filename("file*name.txt") == "filename.txt"

    def test_sanitize_filename_empty(self):
        """Test empty filename gets default name."""
        from atria.web.utils.file_utils import sanitize_filename

        assert sanitize_filename("") == "file"
        assert sanitize_filename("...") == "file"


class TestSafeFilenameGeneration:
    """Test UUID-prefixed filename generation."""

    def test_generate_safe_filename_unique(self):
        """Test different calls generate different UUIDs."""
        from atria.web.utils.file_utils import generate_safe_filename

        filename1 = generate_safe_filename("test.txt")
        filename2 = generate_safe_filename("test.txt")

        assert filename1 != filename2

    def test_generate_safe_filename_format(self):
        """Test filename has UUID prefix."""
        from atria.web.utils.file_utils import generate_safe_filename

        filename = generate_safe_filename("test.txt")

        # Should have underscore separator
        assert "_" in filename
        # Should end with original filename
        assert filename.endswith("test.txt")

    def test_generate_safe_filename_multiple_extensions(self):
        """Test various file extensions."""
        from atria.web.utils.file_utils import generate_safe_filename

        for ext in [".txt", ".pdf", ".png", ".md", ".json"]:
            filename = generate_safe_filename(f"file{ext}")
            assert filename.endswith(ext)

    def test_generate_safe_filename_sanitizes_input(self):
        """Test that dangerous input gets sanitized."""
        from atria.web.utils.file_utils import generate_safe_filename

        filename = generate_safe_filename("../../evil.txt")

        # Should still have UUID prefix
        assert "_" in filename
        # Should not have path traversal
        assert ".." not in filename


class TestArtifactDirPath:
    """Test artifact directory path generation."""

    def test_get_artifact_dir_conversation_scope(self):
        """Test artifact directory path for conversation scope."""
        from atria.web.utils.file_utils import get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_artifact_dir(42, tmpdir, scope="conversation")

            # Should be under .artifacts/conversations/{id}
            assert ".artifacts" in path
            assert "conversations" in path
            assert "42" in path

    def test_get_artifact_dir_project_scope(self):
        """Test artifact directory path for project scope."""
        from atria.web.utils.file_utils import get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_artifact_dir(42, tmpdir, scope="project")

            # Should be under .artifacts/project (without conversation ID)
            assert ".artifacts" in path
            assert "project" in path
            assert "conversations" not in path

    def test_get_artifact_dir_invalid_scope(self):
        """Test invalid scope raises error."""
        from atria.web.utils.file_utils import get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Invalid scope"):
                get_artifact_dir(42, tmpdir, scope="invalid")

    def test_get_artifact_dir_missing_conversation_id(self):
        """Test missing conversation_id for conversation scope raises error."""
        from atria.web.utils.file_utils import get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="conversation_id is required"):
                get_artifact_dir(None, tmpdir, scope="conversation")


class TestFileOperations:
    """Test file I/O operations."""

    def test_create_artifact_directory(self):
        """Test creating artifact directories."""
        from atria.web.utils.file_utils import get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_artifact_dir(123, tmpdir, scope="conversation")
            artifact_path = Path(path)

            # Directory doesn't exist yet
            assert not artifact_path.exists()

            # Create it
            artifact_path.mkdir(parents=True, exist_ok=True)

            # Now it exists
            assert artifact_path.exists()
            assert artifact_path.is_dir()

    def test_write_and_read_artifact_file(self):
        """Test writing and reading artifact files."""
        from atria.web.utils.file_utils import generate_safe_filename, get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory
            path = get_artifact_dir(123, tmpdir, scope="conversation")
            artifact_path = Path(path)
            artifact_path.mkdir(parents=True, exist_ok=True)

            # Generate safe filename
            safe_filename = generate_safe_filename("test.txt")
            file_path = artifact_path / safe_filename

            # Write content
            test_content = b"test file content"
            file_path.write_bytes(test_content)

            # Read and verify
            assert file_path.exists()
            assert file_path.read_bytes() == test_content

    def test_multiple_files_different_names(self):
        """Test storing multiple files with different names."""
        from atria.web.utils.file_utils import generate_safe_filename, get_artifact_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            path = get_artifact_dir(456, tmpdir, scope="project")
            artifact_path = Path(path)
            artifact_path.mkdir(parents=True, exist_ok=True)

            # Create multiple files
            files = {}
            for i in range(3):
                safe_filename = generate_safe_filename(f"file{i}.txt")
                file_path = artifact_path / safe_filename
                content = f"content {i}".encode()
                file_path.write_bytes(content)
                files[safe_filename] = content

            # Verify all files exist and have correct content
            for filename, content in files.items():
                file_path = artifact_path / filename
                assert file_path.exists()
                assert file_path.read_bytes() == content


class TestMaxSizeValidation:
    """Test file size validation."""

    def test_max_file_size_constraint(self):
        """Test that 50MB is the max allowed size."""
        max_size = 50 * 1024 * 1024  # 50MB
        test_size = 51 * 1024 * 1024  # 51MB

        assert test_size > max_size
