import pytest
from pydantic import ValidationError

from atria.core.tasks.payload import SubagentTaskPayload


def _valid() -> dict:
    return {
        "session_id": "s1",
        "owner_id": "u1",
        "subagent_type": "general-purpose",
        "prompt": "do the thing",
        "working_dir": "/tmp/work",
        "config_snapshot": {"model": "gpt-4o"},
    }


def test_payload_round_trips_through_json():
    p = SubagentTaskPayload.model_validate(_valid())
    raw = p.model_dump_json()
    again = SubagentTaskPayload.model_validate_json(raw)
    assert again == p
    assert again.subagent_type == "general-purpose"
    assert again.tool_names is None


def test_payload_rejects_non_serializable_field():
    bad = _valid()
    bad["config_snapshot"] = {"console": object()}  # not JSON-serializable
    p = SubagentTaskPayload.model_validate(bad)
    with pytest.raises((TypeError, ValueError)):
        p.model_dump_json()
