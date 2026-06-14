"""Tests for fs router and path-traversal helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from atria.web.routes.fs import _resolve_safe, router as fs_router


def test_resolve_safe_normal_path(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("hi")
    result = _resolve_safe(tmp_path, "sub/a.txt")
    assert result == (tmp_path / "sub" / "a.txt").resolve()


def test_resolve_safe_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_safe(tmp_path, "../etc/passwd")
    assert exc.value.status_code == 403


def test_resolve_safe_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        _resolve_safe(tmp_path, "/etc/passwd")
    assert exc.value.status_code == 400


def test_resolve_safe_rejects_symlink_escape(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    base = tmp_path
    outside = tmp_path_factory.mktemp("outside_dir")
    (outside / "secret.txt").write_text("nope")
    link = base / "link"
    os.symlink(outside, link)
    with pytest.raises(HTTPException) as exc:
        _resolve_safe(base, "link/secret.txt")
    assert exc.value.status_code == 403


def test_resolve_safe_allows_empty_path_as_root(tmp_path: Path) -> None:
    assert _resolve_safe(tmp_path, "") == tmp_path.resolve()


def _make_app() -> FastAPI:
    from atria.web.dependencies.auth import require_authenticated_user

    app = FastAPI()
    # Override auth dep at the app level — FastAPI captures Depends() at route
    # registration time, so monkeypatching the module attribute won't work.
    app.dependency_overrides[require_authenticated_user] = lambda: {"id": "u1"}
    app.include_router(fs_router)
    return app


@pytest.fixture()
def fake_conv(tmp_path: Path, monkeypatch) -> int:
    """Patch ConversationRepository.get_by_id + get_pool to fake a conversation rooted at tmp_path."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    (tmp_path / "README.md").write_text("# hi\n")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("//")

    async def _get_by_id(self, conv_id):  # noqa: ARG001
        if conv_id == 42:
            return {"id": 42, "working_directory": str(tmp_path)}
        return None

    from atria.db.repositories import conversation_repo

    monkeypatch.setattr(
        conversation_repo.ConversationRepository, "get_by_id", _get_by_id, raising=True
    )

    async def _fake_pool():
        return object()

    from atria.web.routes import fs as fs_module

    monkeypatch.setattr(fs_module, "get_pool", _fake_pool, raising=True)

    return 42


def _client() -> TestClient:
    return TestClient(_make_app())


def test_list_root_returns_entries(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/list")
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == ""
    names = [e["name"] for e in data["entries"]]
    assert "src" in names
    assert "README.md" in names
    assert ".hidden" not in names  # dotfiles hidden by default
    assert "node_modules" not in names  # default-ignore


def test_list_show_hidden_true_includes_dotfiles(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/list?show_hidden=true")
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert ".hidden" in names


def test_list_default_ignore_unconditional(tmp_path: Path, monkeypatch) -> None:
    """`.git` and `node_modules` are always hidden — show_hidden=true must NOT reveal them."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "keep.txt").write_text("x")

    async def _get_by_id(self, conv_id):  # noqa: ARG001
        return {"id": 7, "working_directory": str(tmp_path)}

    from atria.db.repositories import conversation_repo
    from atria.web.routes import fs as fs_module

    monkeypatch.setattr(
        conversation_repo.ConversationRepository, "get_by_id", _get_by_id, raising=True
    )

    async def _fake_pool():
        return object()

    monkeypatch.setattr(fs_module, "get_pool", _fake_pool, raising=True)

    client = _client()
    r = client.get("/api/conversations/7/fs/list?show_hidden=true")
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert ".git" not in names
    assert "node_modules" not in names
    assert "keep.txt" in names


def test_list_nested_path(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/list?path=src")
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert "main.py" in names


def test_list_traversal_blocked(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/list?path=../..")
    assert r.status_code == 403


def test_list_404_unknown_conversation(
    fake_conv: int,
) -> None:  # noqa: ARG001 (fixture activates patches)
    client = _client()
    r = client.get("/api/conversations/9999/fs/list")
    assert r.status_code == 404


def test_list_404_missing_working_dir(tmp_path: Path, monkeypatch) -> None:
    """Conversation exists but working_directory points to a non-existent path → 404."""
    missing = tmp_path / "does_not_exist"

    async def _get_by_id(self, conv_id):  # noqa: ARG001
        return {"id": 11, "working_directory": str(missing)}

    from atria.db.repositories import conversation_repo
    from atria.web.routes import fs as fs_module

    monkeypatch.setattr(
        conversation_repo.ConversationRepository, "get_by_id", _get_by_id, raising=True
    )

    async def _fake_pool():
        return object()

    monkeypatch.setattr(fs_module, "get_pool", _fake_pool, raising=True)

    client = _client()
    r = client.get("/api/conversations/11/fs/list")
    assert r.status_code == 404


def test_read_text_file(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/read?path=README.md")
    assert r.status_code == 200
    assert r.text == "# hi\n"
    assert r.headers["content-type"].startswith("text/markdown")


def test_read_404_missing(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/read?path=nope.txt")
    assert r.status_code == 404


def test_read_traversal_blocked(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/read?path=../escape.txt")
    assert r.status_code == 403


def test_read_oversize_returns_413(fake_conv: int, tmp_path: Path) -> None:
    # tmp_path here is the SAME tmp_path used by fake_conv (pytest reuses per-test).
    big = tmp_path / "big.bin"
    big.write_bytes(b"\0" * (26 * 1024 * 1024))  # 26 MB
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/read?path=big.bin")
    assert r.status_code == 413


def test_read_directory_rejected(fake_conv: int) -> None:
    client = _client()
    r = client.get(f"/api/conversations/{fake_conv}/fs/read?path=src")
    assert r.status_code == 400
