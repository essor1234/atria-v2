"""In-process integration: enqueue -> worker-execute -> collect, no real infra.

Exercises the full background-subagent queue plumbing end-to-end using the
InMemory broker (ENVIRONMENT=pytest), a fakeredis meta client, the REAL
TaskIQClient and REAL run_background_subagent task, and a stubbed
build_runtime_and_deps so no Redis and no live LLM are required. The only piece
this cannot cover in-process is the real subagent LLM run inside the worker —
that is what the documented live e2e (Redis + worker + server + OPENAI_API_KEY)
verifies.
"""
from __future__ import annotations

import atria.core.tasks.tasks as tasks_mod
from atria.core.tasks.broker import broker
from atria.core.tasks.client import TaskIQClient
from atria.core.tasks.payload import SubagentTaskPayload


def test_enqueue_execute_collect_roundtrip(monkeypatch):
    from fakeredis import aioredis as fake_aioredis

    # Stub the worker-side runtime build so no real runtime/LLM is constructed.
    class _Mgr:
        def execute_subagent(self, **kwargs):
            return {
                "success": True,
                "content": f"bg-result:{kwargs['task']}",
                "messages": [],
                "completion_status": "success",
            }

    class _Reg:
        def get_subagent_manager(self):
            return _Mgr()

    class _Suite:
        tool_registry = _Reg()

    monkeypatch.setattr(tasks_mod, "build_runtime_and_deps", lambda p: (_Suite(), "DEPS"))

    client = TaskIQClient(
        broker,
        redis_url="redis://localhost:6379/0",
        orphan_after=1800,
        redis_client=fake_aioredis.FakeRedis(),
    )
    client.startup()
    try:
        payload = SubagentTaskPayload(
            session_id="s1",
            owner_id="u1",
            subagent_type="general-purpose",
            prompt="summarize the readme",
            working_dir="/tmp",
            config_snapshot={},
        )
        task_id = client.enqueue(payload)
        assert isinstance(task_id, str) and task_id

        result = client.await_result(task_id, block=True, timeout_ms=5000)
        assert result["success"] is True
        assert result["status"] == "done"
        assert result["content"] == "bg-result:summarize the readme"
    finally:
        client.shutdown()
