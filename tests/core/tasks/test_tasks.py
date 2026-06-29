import pytest

import atria.core.tasks.tasks as tasks_mod
from atria.core.tasks.payload import SubagentTaskPayload


def _payload() -> SubagentTaskPayload:
    return SubagentTaskPayload(
        session_id="s", owner_id="u", subagent_type="general-purpose",
        prompt="echo", working_dir="/tmp", config_snapshot={},
    )


@pytest.mark.asyncio
async def test_run_background_subagent_returns_result(monkeypatch):
    monkeypatch.setattr(tasks_mod, "build_runtime_and_deps", lambda p: ("RUNTIME", "DEPS"))

    def fake_run(runtime_suite, deps, p):
        assert runtime_suite == "RUNTIME" and deps == "DEPS"
        return {"success": True, "content": "ok", "messages": [],
                "completion_status": "success"}

    monkeypatch.setattr(tasks_mod, "_run_subagent_sync", fake_run)
    result = await tasks_mod.run_background_subagent(_payload().model_dump())
    assert result["success"] is True
    assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_run_background_subagent_handles_builder_error(monkeypatch):
    def boom(p):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tasks_mod, "build_runtime_and_deps", boom)
    result = await tasks_mod.run_background_subagent(_payload().model_dump())
    assert result["success"] is False
    assert "kaboom" in result["content"]
    assert result["completion_status"] == "error"


def test_run_subagent_sync_calls_manager_with_payload():
    """_run_subagent_sync reaches the manager via tool_registry.get_subagent_manager()."""
    captured = {}

    class _Mgr:
        def execute_subagent(self, **kwargs):
            captured.update(kwargs)
            return {"success": True, "content": "done", "messages": [],
                    "completion_status": "success"}

    class _Reg:
        def get_subagent_manager(self):
            return _Mgr()

    class _Suite:
        tool_registry = _Reg()

    p = _payload()
    out = tasks_mod._run_subagent_sync(_Suite(), "DEPS", p)
    assert out["success"] is True
    assert captured["name"] == "general-purpose"
    assert captured["task"] == "echo"
    assert captured["deps"] == "DEPS"
    assert captured["show_spawn_header"] is False
