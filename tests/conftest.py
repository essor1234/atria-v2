"""Shared pytest fixtures for all tests."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.db.connection import get_sessionmaker, init_schema, close_engine
from atria.db.repositories.artifact_repo import ArtifactRepository
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.project_repo import ProjectRepository
from atria.db.repositories.user_repo import UserRepository

collect_ignore_glob = ["manual/*"]


# ── Database Fixtures ──────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Initialize schema and provide a sessionmaker for tests."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL required for database tests")
    await init_schema()
    sm = await get_sessionmaker()
    yield sm
    await close_engine()


# ── Test Project & Conversation Fixtures ──────────────────────────────────


@pytest_asyncio.fixture
async def temp_project(db_session):
    """Create a temporary project with a root directory and workspace path."""
    import uuid

    # Create a persistent temp directory for the project (not auto-cleaned)
    temp_dir = Path(tempfile.gettempdir()) / f"test_project_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    users = UserRepository(db_session)
    projects = ProjectRepository(db_session)

    # Use unique email to avoid conflicts
    unique_email = f"test-project-{uuid.uuid4().hex[:8]}@atria.local"
    uid = await users.upsert_by_email(unique_email)

    # Create project with workspace_path
    pid = await projects.create(
        user_id=uid,
        title="test-project",
        workspace_path=str(temp_dir),
    )

    # Get the created project to verify it has workspace_path
    project = await projects.get_by_id(pid)

    yield {
        "id": pid,
        "user_id": uid,
        "root_directory": str(temp_dir),
        "workspace_path": str(temp_dir),
    }

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)
    await projects.hard_delete(pid)


@pytest_asyncio.fixture
async def temp_conversation(temp_project, db_session):
    """Create a temporary conversation with a working directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        convs = ConversationRepository(db_session)
        cid = await convs.create(
            temp_project["id"],
            temp_project["user_id"],
            "test-conversation",
            "normal",
            working_directory=tmpdir,
        )

        yield {
            "id": cid,
            "project_id": temp_project["id"],
            "user_id": temp_project["user_id"],
            "working_directory": tmpdir,
        }


@pytest_asyncio.fixture
async def uploaded_artifact(temp_conversation, db_session):
    """Create an uploaded artifact (image) with file on disk."""
    repo = ArtifactRepository(db_session)
    working_dir = temp_conversation["working_directory"]

    # Create artifact directory
    artifact_dir = Path(working_dir) / ".artifacts" / "conversations" / str(temp_conversation["id"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake image file
    filename = "test_image.png"
    file_path = artifact_dir / filename
    image_data = b"\x89PNG\r\n\x1a\n" + b"fake_png_data" * 100
    file_path.write_bytes(image_data)

    # Create artifact record
    artifact_id = await repo.create(
        project_id=temp_conversation["project_id"],
        conversation_id=temp_conversation["id"],
        type="image",
        title=filename,
        scope="conversation",
        local_path=f"conversations/{temp_conversation['id']}/{filename}",
    )

    yield {
        "id": artifact_id,
        "filename": filename,
        "file_path": str(file_path),
        "data": image_data,
        "scope": "conversation",
        "type": "image",
    }


@pytest_asyncio.fixture
async def uploaded_pdf(temp_conversation, db_session):
    """Create an uploaded PDF artifact (for unsupported type testing)."""
    repo = ArtifactRepository(db_session)
    working_dir = temp_conversation["working_directory"]

    # Create artifact directory
    artifact_dir = Path(working_dir) / ".artifacts" / "conversations" / str(temp_conversation["id"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake PDF file
    filename = "test_document.pdf"
    file_path = artifact_dir / filename
    pdf_data = b"%PDF-1.4" + b"fake_pdf_data" * 100
    file_path.write_bytes(pdf_data)

    # Create artifact record
    artifact_id = await repo.create(
        project_id=temp_conversation["project_id"],
        conversation_id=temp_conversation["id"],
        type="report",
        title=filename,
        scope="conversation",
        local_path=f"conversations/{temp_conversation['id']}/{filename}",
    )

    yield {
        "id": artifact_id,
        "filename": filename,
        "file_path": str(file_path),
        "data": pdf_data,
        "scope": "conversation",
        "type": "report",
    }


@pytest_asyncio.fixture
async def deleted_artifact(temp_conversation, db_session):
    """Create an artifact marked as deleted."""
    repo = ArtifactRepository(db_session)
    working_dir = temp_conversation["working_directory"]

    # Create artifact directory
    artifact_dir = Path(working_dir) / ".artifacts" / "conversations" / str(temp_conversation["id"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Create a fake image file
    filename = "deleted_image.png"
    file_path = artifact_dir / filename
    image_data = b"\x89PNG\r\n\x1a\n" + b"fake_png_data" * 50
    file_path.write_bytes(image_data)

    # Create artifact record
    artifact_id = await repo.create(
        project_id=temp_conversation["project_id"],
        conversation_id=temp_conversation["id"],
        type="image",
        title=filename,
        scope="conversation",
        local_path=f"conversations/{temp_conversation['id']}/{filename}",
    )

    # Mark as deleted
    await repo.soft_delete(artifact_id)

    yield {
        "id": artifact_id,
        "filename": filename,
        "file_path": str(file_path),
        "data": image_data,
        "scope": "conversation",
        "type": "image",
        "is_deleted": True,
    }


# ── Web Test Client Fixtures ──────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Create a test FastAPI app with artifacts route."""
    from atria.web.dependencies.auth import require_authenticated_user
    from atria.web.routes.artifacts import router as artifacts_router

    app = FastAPI()
    # Override auth dependency to allow tests without authentication
    app.dependency_overrides[require_authenticated_user] = lambda: {"id": "test-user"}
    app.include_router(artifacts_router)
    return app


@pytest.fixture
def artifacts_client() -> TestClient:
    """Create a TestClient for the artifacts API."""
    return TestClient(_make_app())
