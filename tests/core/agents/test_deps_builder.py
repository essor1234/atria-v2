
from atria.core.agents.deps_builder import build_runtime_and_deps
from atria.core.tasks.payload import SubagentTaskPayload


def test_build_runtime_and_deps_headless_autonomous(tmp_path):
    payload = SubagentTaskPayload(
        session_id="s1",
        owner_id="u1",
        subagent_type="general-purpose",
        prompt="noop",
        working_dir=str(tmp_path),
        config_snapshot={},
    )
    runtime_suite, deps = build_runtime_and_deps(payload)

    # The suite must expose a subagent manager (Task 5 runs the subagent through it).
    assert runtime_suite.tool_registry.get_subagent_manager() is not None

    # Autonomous + headless deps.
    assert deps.approval_manager.auto_approve_remaining is True
    assert deps.session_manager is None
    assert deps.mode_manager is not None
