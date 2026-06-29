"""Headless runtime + deps builder for the TaskIQ background worker.

The worker runs subagents in a separate process with no UI, so all dependencies
are built without web/approval/ask-user channels. Subagents run fully autonomously.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from atria.core.tasks.payload import SubagentTaskPayload

if TYPE_CHECKING:
    from atria.core.runtime.services.runtime_service import RuntimeSuite
    from atria.core.agents.subagents.manager import SubAgentDeps


def build_runtime_and_deps(
    payload: SubagentTaskPayload,
) -> tuple[RuntimeSuite, SubAgentDeps]:
    """Rebuild a HEADLESS runtime suite + autonomous subagent deps from a payload.

    Used by the TaskIQ worker to run a background subagent in a separate process
    with no UI. The subagent runs fully autonomously (auto-approve) because the
    worker has no interactive approval/ask-user channel.

    Note: ``payload.config_snapshot`` is currently unused — disk config loaded via
    ``ConfigManager`` is the source of truth. A later task can layer it in.

    Args:
        payload: Serialisable task payload produced by the gateway.

    Returns:
        A ``(runtime_suite, deps)`` tuple ready for ``execute_subagent``.
    """
    # --- Local imports avoid heavy cost on module load ---
    from atria.core.runtime.config import ConfigManager
    from atria.core.runtime import ModeManager
    from atria.core.runtime.services.runtime_service import RuntimeService
    from atria.core.runtime.approval.manager import ApprovalManager
    from atria.core.agents.subagents.manager import SubAgentDeps
    from atria.core.context_engineering.history.undo_manager import UndoManager

    # Tool implementations — import paths verified against real class definitions.
    from atria.core.context_engineering.tools.implementations.file_ops import FileOperations
    from atria.core.context_engineering.tools.implementations.write_tool import WriteTool
    from atria.core.context_engineering.tools.implementations.edit_tool.tool import EditTool
    from atria.core.context_engineering.tools.implementations.bash_tool.tool import BashTool
    from atria.core.context_engineering.tools.implementations.web_fetch_tool import WebFetchTool
    from atria.core.context_engineering.tools.implementations.web_search_tool import WebSearchTool
    from atria.core.context_engineering.tools.implementations.notebook_edit_tool import (
        NotebookEditTool,
    )

    wd = Path(payload.working_dir)

    config_manager = ConfigManager(working_dir=wd)
    config = config_manager.get_config()
    mode_manager = ModeManager()

    # Construct tools — shapes match agent_executor.py:246-251.
    file_ops = FileOperations(config, wd)
    write_tool = WriteTool(config, wd)
    edit_tool = EditTool(config, wd)
    bash_tool = BashTool(config, wd)
    web_fetch_tool = WebFetchTool(config, wd)
    web_search_tool = WebSearchTool(config, wd)
    notebook_edit_tool = NotebookEditTool(wd)

    runtime_service = RuntimeService(config_manager, mode_manager)
    runtime_suite = runtime_service.build_suite(
        file_ops=file_ops,
        write_tool=write_tool,
        edit_tool=edit_tool,
        bash_tool=bash_tool,
        web_fetch_tool=web_fetch_tool,
        web_search_tool=web_search_tool,
        notebook_edit_tool=notebook_edit_tool,
        ask_user_tool=None,  # headless: no interactive ask-user channel
        mcp_manager=None,    # MVP: no MCP tools in the worker
    )

    # Auto-approve all operations — background subagents run without a user present.
    approval_manager = ApprovalManager()
    approval_manager.auto_approve_remaining = True

    undo_manager = UndoManager()  # no session_dir: worker doesn't persist undo history

    deps = SubAgentDeps(
        mode_manager=mode_manager,
        approval_manager=approval_manager,
        undo_manager=undo_manager,
        session_manager=None,  # worker does NOT reload parent session; subagent runs
                               # fresh on payload.prompt. execute_subagent never reads
                               # deps.session_manager (verified).
    )

    # Blackboard (Phase 2b): when the payload carries a blackboard task id, attach a
    # per-solver handle at this thread_id so the NOTE tool + Shared Lessons injection
    # are active for the run. Accelerant — None when unavailable. The caller
    # (run_background_subagent) tears this handle down after the run.
    if payload.blackboard_task_id:
        from atria.core.blackboard.provision import make_solver_blackboard

        deps.blackboard = make_solver_blackboard(
            config,
            task_id=payload.blackboard_task_id,
            owner_id=payload.owner_id,
            thread_id=payload.thread_id,
        )

    return runtime_suite, deps
