"""Tests that the NOTE tool schema is gated on config.blackboard.enabled.

When the flag is False (default), the NOTE schema must not appear in the
list built by ToolSchemaBuilder — zero tokens wasted, zero dead tool calls.
When True, NOTE must be present.
"""
from __future__ import annotations

from atria.core.agents.components.schemas.normal_builder import ToolSchemaBuilder


def _tool_names(schemas: list[dict]) -> list[str]:
    return [s["function"]["name"] for s in schemas]


def test_note_absent_when_blackboard_disabled() -> None:
    """With blackboard_enabled=False (the default) NOTE must not appear."""
    builder = ToolSchemaBuilder(tool_registry=None, blackboard_enabled=False)
    names = _tool_names(builder.build())
    assert "NOTE" not in names, f"NOTE found in schema list despite blackboard disabled: {names}"


def test_note_absent_by_default() -> None:
    """Default construction (no blackboard_enabled kwarg) must also omit NOTE."""
    builder = ToolSchemaBuilder(tool_registry=None)
    names = _tool_names(builder.build())
    assert "NOTE" not in names


def test_note_present_when_blackboard_enabled() -> None:
    """With blackboard_enabled=True, NOTE must appear exactly once."""
    builder = ToolSchemaBuilder(tool_registry=None, blackboard_enabled=True)
    names = _tool_names(builder.build())
    assert "NOTE" in names, "NOTE schema missing despite blackboard enabled"
    assert names.count("NOTE") == 1, "NOTE schema appears more than once"


def test_other_tools_unaffected_by_flag() -> None:
    """Toggling blackboard_enabled must not drop or duplicate any other tool."""
    disabled = _tool_names(ToolSchemaBuilder(tool_registry=None, blackboard_enabled=False).build())
    enabled = _tool_names(ToolSchemaBuilder(tool_registry=None, blackboard_enabled=True).build())

    # Every tool in the disabled list must also be in the enabled list.
    for name in disabled:
        assert name in enabled, f"Tool {name!r} disappeared when blackboard was enabled"

    # The only extra tool when enabled should be NOTE.
    extras = [n for n in enabled if n not in disabled]
    assert extras == ["NOTE"], f"Unexpected extra tools when blackboard enabled: {extras}"
