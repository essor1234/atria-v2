"""Publish-on-append behaviour for BlackboardStore."""
from __future__ import annotations

import json
from typing import Any

import pytest

from atria.core.blackboard.models import Note
from atria.core.blackboard.store import BlackboardStore


class FakeRedis:
    def __init__(self, publish_should_fail: bool = False) -> None:
        self.rpush_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.publish_calls: list[tuple[str, str]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self._publish_fail = publish_should_fail

    async def rpush(self, key: str, *values: Any) -> int:
        self.rpush_calls.append((key, values))
        return len(values)

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))

    async def publish(self, channel: str, payload: str) -> int:
        if self._publish_fail:
            raise RuntimeError("redis down")
        self.publish_calls.append((channel, payload))
        return 1


@pytest.mark.asyncio
async def test_append_publishes_each_note() -> None:
    redis = FakeRedis()
    store = BlackboardStore(redis, task_id="bb_abc", ttl=60)
    notes = [
        Note(type="fact", content="hello", thread_id=1, ts=1.0),
        Note(type="decision", content="choose A", thread_id=1, ts=2.0),
    ]

    await store.append(notes)

    assert len(redis.publish_calls) == 2
    channels = {c for c, _ in redis.publish_calls}
    assert channels == {"atria:bb:bb_abc:notes"}
    payload = json.loads(redis.publish_calls[0][1])
    assert payload == {
        "task_id": "bb_abc",
        "thread_id": 1,
        "type": "fact",
        "content": "hello",
        "ts": 1.0,
    }


@pytest.mark.asyncio
async def test_append_survives_publish_failure() -> None:
    redis = FakeRedis(publish_should_fail=True)
    store = BlackboardStore(redis, task_id="bb_xyz", ttl=60)

    await store.append([Note(type="fact", content="x", thread_id=0, ts=0.0)])

    assert len(redis.rpush_calls) == 1  # append still committed
    assert redis.publish_calls == []
