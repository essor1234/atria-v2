"""Tests for atria.core.tasks.meta using fakeredis (no real Redis needed)."""
from __future__ import annotations

import asyncio

import pytest
from fakeredis import aioredis as fake_aioredis

from atria.core.tasks import meta


@pytest.fixture
def redis():
    """Provide a fresh FakeRedis instance for each test."""
    return fake_aioredis.FakeRedis()


def run(coro):
    """Run a coroutine synchronously for non-async test helpers."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.asyncio
async def test_record_enqueue_then_age_returns_positive_float():
    """age_seconds returns a small positive float right after enqueue."""
    r = fake_aioredis.FakeRedis()
    await meta.record_enqueue(r, task_id="task-abc", session_id="sess-1")
    age = await meta.age_seconds(r, task_id="task-abc")
    assert age is not None
    assert 0.0 <= age < 5.0  # should be near-instant


@pytest.mark.asyncio
async def test_age_seconds_unknown_task_returns_none():
    """age_seconds returns None when no meta entry exists for the task."""
    r = fake_aioredis.FakeRedis()
    result = await meta.age_seconds(r, task_id="never-recorded")
    assert result is None


@pytest.mark.asyncio
async def test_reap_orphans_removes_stale_entry_and_returns_task_id():
    """reap_orphans with max_age=0 immediately reaps a freshly enqueued entry."""
    r = fake_aioredis.FakeRedis()
    await meta.record_enqueue(r, task_id="task-stale", session_id="sess-2")
    # max_age=0 means any entry (even just enqueued) is considered stale
    reaped = await meta.reap_orphans(r, max_age=0.0)
    assert "task-stale" in reaped
    # Entry should now be gone
    age_after = await meta.age_seconds(r, task_id="task-stale")
    assert age_after is None


@pytest.mark.asyncio
async def test_reap_orphans_keeps_fresh_entry():
    """reap_orphans with a large max_age does not remove a fresh entry."""
    r = fake_aioredis.FakeRedis()
    await meta.record_enqueue(r, task_id="task-fresh", session_id="sess-3")
    reaped = await meta.reap_orphans(r, max_age=9999.0)
    assert "task-fresh" not in reaped
    # Entry should still be present
    age = await meta.age_seconds(r, task_id="task-fresh")
    assert age is not None


@pytest.mark.asyncio
async def test_reap_orphans_empty_store_returns_empty_list():
    """reap_orphans on an empty store returns an empty list."""
    r = fake_aioredis.FakeRedis()
    reaped = await meta.reap_orphans(r, max_age=0.0)
    assert reaped == []
