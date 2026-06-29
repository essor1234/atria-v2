"""Tests for BackgroundMixin on SubAgentManager."""
from __future__ import annotations

from atria.core.agents.subagents.manager.manager import SubAgentManager


class _FakeClient:
    def __init__(self):
        self.enqueued = None

    def enqueue(self, payload):
        self.enqueued = payload
        return "task-xyz"

    def await_result(self, task_id, block=True, timeout_ms=30000):
        assert task_id == "task-xyz"
        return {"success": True, "content": "bg done", "status": "done",
                "messages": [], "completion_status": "success"}


def _make_manager():
    """Build a minimal manager; stub heavy init as needed."""
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _FakeClient()
    return mgr


def test_get_background_task_output_delegates():
    mgr = _make_manager()
    out = mgr.get_background_task_output("task-xyz", block=True, timeout=5000)
    assert out["success"] is True
    assert out["content"] == "bg done"


def test_execute_subagent_background_enqueues():
    mgr = _make_manager()
    result = mgr.execute_subagent_background(
        name="general-purpose",
        task="do bg work",
        owner_id="u1",
        session_id="s1",
        working_dir="/tmp",
        config_snapshot={},
        tool_call_id="tc1",
    )
    assert result["task_id"] == "task-xyz"
    assert result["status"] == "running"
    assert mgr._task_client.enqueued.subagent_type == "general-purpose"


def test_get_background_task_output_running():
    """Status 'running' maps to success=False."""

    class _RunningClient:
        def await_result(self, task_id, block=True, timeout_ms=30000):
            return {"success": False, "status": "running"}

    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _RunningClient()
    out = mgr.get_background_task_output("task-abc", block=False, timeout=0)
    assert out["success"] is False
    assert out["status"] == "running"
    assert out["output"] is None
    assert out["task_id"] == "task-abc"


def test_get_background_task_output_failed():
    """Failed status maps to success=False with error."""

    class _FailClient:
        def await_result(self, task_id, block=True, timeout_ms=30000):
            return {"success": False, "status": "failed", "error": "boom"}

    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _FailClient()
    out = mgr.get_background_task_output("task-fail")
    assert out["success"] is False
    assert out["error"] == "boom"
    assert out["output"] is None


def test_get_background_task_output_no_client():
    """Returns error dict when task client is not configured."""
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = None
    out = mgr.get_background_task_output("task-xyz")
    assert out["success"] is False
    assert "not configured" in out["error"]


def test_set_task_client():
    """set_task_client wires the client onto the manager."""
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = None
    client = _FakeClient()
    mgr.set_task_client(client)
    assert mgr._task_client is client


def _make_sync_manager(client):
    """Build a manager with the minimal attrs needed to reach the sync body."""
    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = client
    mgr._hook_manager = None
    mgr._agents = {}
    mgr._working_dir = "/tmp"
    mgr._config = None
    mgr._tool_registry = None
    mgr._mode_manager = None
    mgr._env_context = None
    mgr._all_tool_names = []
    return mgr


def test_execute_subagent_sync_default_skips_background():
    """When run_in_background=False (default), the background branch is not entered."""
    from atria.core.agents.subagents.manager.manager import SubAgentDeps

    mgr = _make_sync_manager(_FakeClient())
    deps = SubAgentDeps(mode_manager=None, approval_manager=None, undo_manager=None)
    # Falls through to sync path → "Unknown subagent" (proves bg branch was skipped)
    result = mgr.execute_subagent(name="nonexistent", task="t", deps=deps)
    assert result["success"] is False
    assert "Unknown subagent" in result.get("error", "")
    # background key must NOT be present (sync path)
    assert "background" not in result


def test_execute_subagent_falls_through_on_enqueue_error():
    """run_in_background=True + enqueue raises → warning logged, sync path runs."""
    from atria.core.agents.subagents.manager.manager import SubAgentDeps

    class _BrokenClient:
        def enqueue(self, payload):
            raise ConnectionError("Redis down")

    mgr = _make_sync_manager(_BrokenClient())
    deps = SubAgentDeps(mode_manager=None, approval_manager=None, undo_manager=None)
    # Exception must NOT propagate; falls through to sync body → "Unknown subagent"
    result = mgr.execute_subagent(
        name="nonexistent", task="t", deps=deps, run_in_background=True
    )
    assert result["success"] is False
    assert "Unknown subagent" in result.get("error", "")
    assert "background" not in result


def test_get_background_task_output_completed_but_failed():
    """Completed (status='done') but success=False surfaces real reason as 'failed'."""

    class _DoneFailClient:
        def await_result(self, task_id, block=True, timeout_ms=30000):
            return {
                "success": False,
                "status": "done",
                "content": "background subagent failed: boom",
                "error": None,
            }

    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _DoneFailClient()
    out = mgr.get_background_task_output("task-done-fail")
    assert out["success"] is False
    assert out["status"] == "failed"
    assert out["error"] == "background subagent failed: boom"
    assert out["output"] is None


def test_get_background_task_output_expired():
    """Expired status falls into the non-success branch with its status preserved."""

    class _ExpiredClient:
        def await_result(self, task_id, block=True, timeout_ms=30000):
            return {"success": False, "status": "expired", "error": "result expired"}

    mgr = SubAgentManager.__new__(SubAgentManager)
    mgr._task_client = _ExpiredClient()
    out = mgr.get_background_task_output("task-exp")
    assert out["success"] is False
    assert out["status"] == "expired"
    assert out["error"] == "result expired"
    assert out["output"] is None
