"""Blackboard subscriber → WS broadcast."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from atria.web.blackboard_subscriber import BlackboardSubscriber


class FakePubSub:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)

    async def psubscribe(self, pattern: str) -> None:  # noqa: ARG002
        return None

    async def punsubscribe(self, pattern: str) -> None:  # noqa: ARG002
        return None

    async def get_message(
        self, ignore_subscribe_messages: bool = True, timeout: float = 1.0
    ) -> dict | None:
        if self._messages:
            return self._messages.pop(0)
        return None

    async def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self, pubsub: FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> FakePubSub:
        return self._pubsub


class FakeBroadcaster:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.messages.append(message)


def _msg(task_id: str, thread_id: int, content: str) -> dict:
    payload = {
        "task_id": task_id,
        "thread_id": thread_id,
        "type": "fact",
        "content": content,
        "ts": 1.0,
    }
    return {
        "type": "pmessage",
        "pattern": b"atria:bb:*:notes",
        "channel": f"atria:bb:{task_id}:notes".encode(),
        "data": json.dumps(payload).encode(),
    }


@pytest.mark.asyncio
async def test_forwards_message_as_blackboard_note_event() -> None:
    pubsub = FakePubSub([_msg("bb_1", 0, "hello")])
    redis = FakeRedis(pubsub)
    bcast = FakeBroadcaster()

    sub = BlackboardSubscriber(redis, bcast)
    task = asyncio.create_task(sub.run(iterations=1))
    await task

    assert len(bcast.messages) == 1
    msg = bcast.messages[0]
    assert msg["type"] == "blackboard.note"
    assert msg["data"]["task_id"] == "bb_1"
    assert msg["data"]["content"] == "hello"


@pytest.mark.asyncio
async def test_throttle_drops_middle_of_burst() -> None:
    burst = [_msg("bb_2", 0, f"n{i}") for i in range(30)]
    pubsub = FakePubSub(burst)
    bcast = FakeBroadcaster()

    sub = BlackboardSubscriber(FakeRedis(pubsub), bcast, max_per_second=10)
    await sub.run(iterations=len(burst))

    # first + up to (max_per_second - 1) more per second window; strictly less than input.
    assert 1 <= len(bcast.messages) <= 10
    assert bcast.messages[0]["data"]["content"] == "n0"
