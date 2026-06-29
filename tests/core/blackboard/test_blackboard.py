import asyncio

import pytest

from atria.core.blackboard.blackboard import Blackboard, BlackboardHandle
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


def test_handle_degrades_and_shutdown_is_idempotent():
    class _BoomStore:
        async def append(self, notes):
            raise RuntimeError("redis down")

        async def read_all(self):
            raise RuntimeError("redis down")

    handle = BlackboardHandle(Blackboard(_BoomStore(), thread_id=0, window_tokens=2000))
    try:
        assert handle.write([{"type": "FACT", "content": "x"}]) == "blackboard unavailable"
        assert handle.render() == ""
    finally:
        handle.shutdown()
    handle.shutdown()  # idempotent: a second shutdown must not raise


def test_handle_submit_times_out_and_degrades() -> None:
    """_submit respects _op_timeout: a slow store causes write/render to degrade gracefully.

    The store deliberately sleeps longer than _op_timeout.  The bridge must
    not block forever — it must raise concurrent.futures.TimeoutError (an
    Exception subclass) which is caught by the write/render try/except blocks
    that return soft-failure values instead.
    """
    SLEEP = 2.0  # store sleeps for 2 seconds
    TIMEOUT = 0.1  # we only wait 0.1 s before timing out

    class _SlowStore:
        async def append(self, notes):  # noqa: D401
            await asyncio.sleep(SLEEP)

        async def read_all(self):
            await asyncio.sleep(SLEEP)
            return []

    bb = Blackboard(_SlowStore(), thread_id=0, window_tokens=2000)
    handle = BlackboardHandle(bb)
    handle._op_timeout = TIMEOUT  # shrink timeout so the test is fast

    try:
        result = handle.write([{"type": "FACT", "content": "x"}])
        assert result == "blackboard unavailable", (
            f"Expected soft-failure from timed-out write, got: {result!r}"
        )
        rendered = handle.render()
        assert rendered == "", (
            f"Expected empty string from timed-out render, got: {rendered!r}"
        )
    finally:
        handle.shutdown()
