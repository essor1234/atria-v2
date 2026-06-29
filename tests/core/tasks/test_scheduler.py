"""Tests for atria.core.tasks.scheduler."""
import pytest

import atria.core.tasks.scheduler as sched
from atria.core.tasks import meta


@pytest.mark.asyncio
async def test_reap_orphan_tasks_reaps_stale_entry(monkeypatch):
    """Janitor reaps a stale meta entry and returns count >= 1."""
    from fakeredis import aioredis as fake_aioredis

    fake = fake_aioredis.FakeRedis()
    # Janitor builds its client via aioredis.from_url — force it to our shared fake.
    monkeypatch.setattr(sched.aioredis, "from_url", lambda *a, **k: fake)
    # Make every recorded entry "stale" so it gets reaped this run.
    monkeypatch.setattr(sched, "_orphan_after", lambda: 0)

    await meta.record_enqueue(fake, "task-1", "sess-1")
    count = await sched.reap_orphan_tasks()
    assert count >= 1
    # The meta entry is gone after reaping.
    assert await meta.age_seconds(fake, "task-1") is None


def test_scheduler_module_imports():
    """Scheduler and janitor task are importable and non-None."""
    from atria.core.tasks.scheduler import reap_orphan_tasks, scheduler

    assert scheduler is not None
    assert reap_orphan_tasks is not None
