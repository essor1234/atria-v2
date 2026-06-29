import pytest

from atria.core.blackboard.archive import archive_to_postgres
from atria.core.blackboard.models import Note


@pytest.mark.asyncio
async def test_archive_writes_rows(monkeypatch):
    captured = []

    class _Session:
        def add(self, obj):
            captured.append(obj)

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    def _factory():
        return _Session()

    n = await archive_to_postgres(_factory, "t1", "u1", [Note("FACT", "a", 0, 1.0)])
    assert n == 1
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_archive_swallows_failure(monkeypatch):
    def _factory():
        raise RuntimeError("db down")

    n = await archive_to_postgres(_factory, "t1", "u1", [Note("FACT", "a", 0, 1.0)])
    assert n == 0  # best-effort, no raise
