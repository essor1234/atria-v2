"""Schema shape for spawn_subagent after the strategy rewire."""
from __future__ import annotations

from atria.core.agents.subagents.task_tool import create_task_tool_schema


class _FakeConfig:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description


class _FakeManager:
    def get_agent_configs(self) -> list[_FakeConfig]:
        return [_FakeConfig("solver", "Race worktree solvers.")]


def test_strategy_field_is_present() -> None:
    schema = create_task_tool_schema(_FakeManager())
    props = schema["function"]["parameters"]["properties"]

    assert "strategy" in props
    assert props["strategy"]["type"] == "string"
    assert set(props["strategy"]["enum"]) == {"direct", "divide", "parallel"}
    assert props["strategy"].get("default") == "direct"


def test_strategy_not_required() -> None:
    schema = create_task_tool_schema(_FakeManager())
    required = schema["function"]["parameters"]["required"]
    assert "strategy" not in required
    assert "subagent_type" in required  # unchanged: still required in schema
