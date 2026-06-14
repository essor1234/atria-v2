"""Real-DB tests for ArtifactRepository on SQLAlchemy ORM."""

from __future__ import annotations

import os
import pytest
import pytest_asyncio

from atria.db.connection import get_sessionmaker, init_schema, close_engine
from atria.db.repositories.artifact_repo import ArtifactRepository
from atria.db.repositories.conversation_repo import ConversationRepository
from atria.db.repositories.project_repo import ProjectRepository
from atria.db.repositories.user_repo import UserRepository


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL"),
        reason="DATABASE_URL required for real-Postgres ORM tests",
    ),
]


@pytest_asyncio.fixture
async def sm():
    await init_schema()
    sm = await get_sessionmaker()
    yield sm
    await close_engine()


async def _ctx(sm):
    users = UserRepository(sm)
    projects = ProjectRepository(sm)
    convs = ConversationRepository(sm)
    uid = await users.upsert_by_email("orm-art@atria.local")
    pid = await projects.get_or_create(uid, "art-project")
    cid = await convs.create(pid, uid, "art-conv", "normal")
    return pid, cid


async def test_create_and_get_roundtrip(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)
    aid = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="hello.txt",
        payload_ref="/tmp/hello.txt",
        preview={"snippet": "hello"},
    )
    row = await repo.get_by_id(aid)
    assert row is not None
    assert row["title"] == "hello.txt"
    assert row["preview"] == {"snippet": "hello"}


async def test_upsert_by_ref_is_idempotent(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)
    a = await repo.upsert_by_ref(pid, cid, "/tmp/x.md", "file")
    b = await repo.upsert_by_ref(pid, cid, "/tmp/x.md", "file")
    assert a == b


async def test_soft_delete_idempotent(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)
    aid = await repo.create(project_id=pid, type="file", conversation_id=cid)
    assert await repo.soft_delete(aid) is True
    assert await repo.soft_delete(aid) is False


async def test_create_with_scope_and_local_path(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)
    aid = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="scoped.txt",
        payload_ref="/tmp/scoped.txt",
        scope="conversation",
        local_path="/home/user/scoped.txt",
    )
    row = await repo.get_by_id(aid)
    assert row is not None
    assert row["scope"] == "conversation"
    assert row["local_path"] == "/home/user/scoped.txt"


async def test_list_by_conversation_and_scope(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)

    # Create artifacts with different scopes
    aid1 = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="file1.txt",
        scope="conversation",
        local_path="/path/file1.txt",
    )
    await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="file2.txt",
        scope="project",
        local_path="/path/file2.txt",
    )
    aid3 = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="file3.txt",
        scope="conversation",
        local_path="/path/file3.txt",
    )

    # Filter by conversation scope
    rows = await repo.list_by_conversation_and_scope(cid, "conversation")
    assert len(rows) == 2
    assert all(r["scope"] == "conversation" for r in rows)
    assert {r["id"] for r in rows} == {aid1, aid3}


async def test_list_by_project_and_scope(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)

    # Create artifacts with different scopes
    aid1 = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="proj_file1.txt",
        scope="project",
        local_path="/path/proj_file1.txt",
    )
    await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="proj_file2.txt",
        scope="conversation",
        local_path="/path/proj_file2.txt",
    )
    aid3 = await repo.create(
        project_id=pid,
        type="file",
        conversation_id=cid,
        title="proj_file3.txt",
        scope="project",
        local_path="/path/proj_file3.txt",
    )

    # Filter by project scope
    rows = await repo.list_by_project_and_scope(pid, "project")
    assert len(rows) == 2
    assert all(r["scope"] == "project" for r in rows)
    assert {r["id"] for r in rows} == {aid1, aid3}


async def test_upsert_by_ref_with_scope_and_local_path(sm):
    pid, cid = await _ctx(sm)
    repo = ArtifactRepository(sm)

    # First upsert with scope and local_path
    aid = await repo.upsert_by_ref(
        pid,
        cid,
        "/tmp/scoped.md",
        "file",
        scope="conversation",
        local_path="/home/user/scoped.md",
    )

    row = await repo.get_by_id(aid)
    assert row["scope"] == "conversation"
    assert row["local_path"] == "/home/user/scoped.md"

    # Second upsert should be idempotent
    aid2 = await repo.upsert_by_ref(
        pid,
        cid,
        "/tmp/scoped.md",
        "file",
        scope="conversation",
        local_path="/home/user/scoped.md",
    )
    assert aid == aid2
