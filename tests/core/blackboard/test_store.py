import pytest

from atria.core.blackboard.models import Note
from atria.core.blackboard.store import BlackboardStore


@pytest.mark.asyncio
async def test_append_then_read_roundtrip():
    from fakeredis import aioredis as fake_aioredis

    r = fake_aioredis.FakeRedis()
    store = BlackboardStore(r, task_id="t1", ttl=60)
    await store.append([Note("FACT", "a", 0, 1.0), Note("TRIED", "b", 0, 2.0)])
    await store.append([Note("OBSERVED", "c", 1, 3.0)])
    notes = await store.read_all()
    assert [n.content for n in notes] == ["a", "b", "c"]
    assert notes[2].thread_id == 1


@pytest.mark.asyncio
async def test_read_all_empty_is_empty_list():
    from fakeredis import aioredis as fake_aioredis

    store = BlackboardStore(fake_aioredis.FakeRedis(), task_id="none", ttl=60)
    assert await store.read_all() == []
