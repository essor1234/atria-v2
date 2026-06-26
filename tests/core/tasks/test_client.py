import os

import pytest

from atria.core.tasks.broker import make_broker
from atria.core.tasks.client import TaskIQClient
from atria.core.tasks.payload import SubagentTaskPayload


@pytest.fixture
def payload() -> SubagentTaskPayload:
    return SubagentTaskPayload(
        session_id="s1",
        owner_id="u1",
        subagent_type="general-purpose",
        prompt="hi",
        working_dir="/tmp",
        config_snapshot={},
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "pytest")
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)

    # Register an in-memory task that echoes a success result.
    @broker.task(task_name="atria.core.tasks.tasks.run_background_subagent")
    async def _fake(payload: dict) -> dict:
        return {
            "success": True,
            "content": "done:" + payload["prompt"],
            "messages": [],
            "completion_status": "success",
        }

    c = TaskIQClient(broker, redis_url="redis://localhost:6379/0", orphan_after=1800)
    c.startup()
    yield c
    c.shutdown()


def test_enqueue_returns_task_id_and_result(client, payload):
    task_id = client.enqueue(payload)
    assert isinstance(task_id, str) and task_id
    result = client.await_result(task_id, block=True, timeout_ms=5000)
    assert result["success"] is True
    assert result["content"] == "done:hi"
    assert result["status"] == "done"


def test_await_nonblocking_when_not_ready_returns_running(client, payload):
    # Unknown id, non-blocking → running (not yet old enough to be orphaned)
    result = client.await_result("does-not-exist", block=False, timeout_ms=0)
    assert result["status"] in {"running", "failed"}
