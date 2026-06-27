import pytest

from atria.core.blackboard.blackboard import Blackboard
from atria.core.blackboard.store import BlackboardStore


def _bb(thread_id=0):
    from fakeredis import aioredis as fake_aioredis

    store = BlackboardStore(fake_aioredis.FakeRedis(), task_id="t1", ttl=60)
    return Blackboard(store, thread_id=thread_id, window_tokens=2000)


@pytest.mark.asyncio
async def test_write_verifies_then_render_shows_kept_notes():
    bb = _bb(thread_id=2)
    status = await bb.write([{"type": "fact", "content": "found it"},
                             {"type": "BOGUS", "content": "drop me"}])
    assert status == "ok:1/2"
    digest = await bb.render()
    assert "[t2/FACT] found it" in digest
    assert "drop me" not in digest


@pytest.mark.asyncio
async def test_write_none_keeps_nothing():
    bb = _bb()
    status = await bb.write([])
    assert status == "ok:0/0"
    assert await bb.render() == ""


@pytest.mark.asyncio
async def test_write_degrades_when_store_raises():
    class _BoomStore:
        async def append(self, notes):
            raise RuntimeError("redis down")
        async def read_all(self):
            raise RuntimeError("redis down")

    bb = Blackboard(_BoomStore(), thread_id=0, window_tokens=2000)
    assert await bb.write([{"type": "FACT", "content": "x"}]) == "blackboard unavailable"
    assert await bb.render() == ""
