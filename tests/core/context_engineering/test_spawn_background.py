from atria.core.context_engineering.tools.registry import ToolRegistry


class _Mgr:
    def execute_subagent(self, **kwargs):
        assert kwargs.get("run_in_background") is True
        return {
            "success": True,
            "background": True,
            "status": "running",
            "task_id": "bg-1",
            "subagent_type": kwargs["name"],
        }

    def get_background_task_output(self, task_id, block=True, timeout=30000):
        return {
            "success": True,
            "status": "done",
            "output": "result text",
            "content": "result text",
            "completion_status": "success",
        }


def _registry_with_manager():
    reg = ToolRegistry.__new__(ToolRegistry)  # bypass heavy __init__
    reg._subagent_manager = _Mgr()
    return reg


def test_spawn_subagent_background_returns_task_id():
    reg = _registry_with_manager()
    out = reg._execute_spawn_subagent(
        {"prompt": "do it", "subagent_type": "general-purpose", "run_in_background": True},
        context=None,
        tool_call_id="tc-1",
    )
    assert out["task_id"] == "bg-1"
    assert out["status"] == "running"
    assert "[BACKGROUND STARTED]" in out["output"]


def test_get_subagent_output_returns_result():
    reg = _registry_with_manager()
    out = reg._get_subagent_output({"task_id": "bg-1", "block": True, "timeout": 5000})
    assert out["success"] is True
    assert out["output"] == "result text"
