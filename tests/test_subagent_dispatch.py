"""Strategy routing in _execute_spawn_subagent."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from atria.core.context_engineering.tools.registry_mixins.subagent_ops import (
    SubagentOpsMixin,
)


class _Holder(SubagentOpsMixin):
    def __init__(self, subagent_manager=None, file_ops=None) -> None:
        self._subagent_manager = subagent_manager
        self.file_ops = file_ops


def _ctx(**kw):
    base = dict(
        mode_manager=None,
        approval_manager=None,
        undo_manager=None,
        session_manager=None,
        ui_callback=None,
        task_monitor=None,
        divide_orchestrator=None,
        parallel_orchestrator=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_direct_strategy_calls_subagent_manager() -> None:
    mgr = MagicMock()
    mgr.execute_subagent.return_value = {"success": True, "content": "ok", "messages": []}
    holder = _Holder(subagent_manager=mgr)

    result = holder._execute_spawn_subagent(
        {"description": "d", "prompt": "task", "subagent_type": "solver"},
        context=_ctx(),
    )

    mgr.execute_subagent.assert_called_once()
    assert result["success"] is True


def test_divide_strategy_calls_divide_orchestrator() -> None:
    div = MagicMock()
    div.start.return_value = "job_div_1"
    div.collect.return_value = {"status": "done", "summary": "3/3 tasks done"}
    holder = _Holder(subagent_manager=MagicMock())

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "big task",
            "subagent_type": "solver",
            "strategy": "divide",
        },
        context=_ctx(divide_orchestrator=div),
    )

    div.start.assert_called_once()
    assert result["success"] is True
    assert result["job_id"] == "job_div_1"
    assert result["strategy"] == "divide"


def test_parallel_strategy_calls_parallel_orchestrator() -> None:
    par = MagicMock()
    par.start.return_value = "job_par_1"
    par.collect.return_value = {"status": "done", "applied": True, "reasoning": "r"}
    holder = _Holder(subagent_manager=MagicMock(), file_ops=SimpleNamespace(working_dir="."))

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "solve X",
            "subagent_type": "solver",
            "strategy": "parallel",
        },
        context=_ctx(parallel_orchestrator=par),
    )

    par.start.assert_called_once()
    assert result["success"] is True
    assert result["job_id"] == "job_par_1"
    assert result["strategy"] == "parallel"


def test_dispatch_strategy_without_orchestrator_returns_fallback_hint() -> None:
    holder = _Holder(subagent_manager=MagicMock())

    result = holder._execute_spawn_subagent(
        {
            "description": "d",
            "prompt": "x",
            "subagent_type": "solver",
            "strategy": "divide",
        },
        context=_ctx(),  # divide_orchestrator is None
    )

    assert result["success"] is False
    assert 'strategy="direct"' in result["error"]


def test_empty_task_rejected_for_all_strategies() -> None:
    holder = _Holder(subagent_manager=MagicMock())
    for strat in ("direct", "divide", "parallel"):
        result = holder._execute_spawn_subagent(
            {"description": "d", "prompt": "", "subagent_type": "solver", "strategy": strat},
            context=_ctx(divide_orchestrator=MagicMock(), parallel_orchestrator=MagicMock()),
        )
        assert result["success"] is False
        assert "prompt" in (result.get("error") or "").lower()
