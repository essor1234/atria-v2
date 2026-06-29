"""Parallel / divide / unified ``solve`` orchestration for the tool registry."""

from __future__ import annotations

from typing import Any


class OrchestrationOpsMixin:
    """Lazily-built parallel & divide orchestrators and their tool handlers."""

    def _get_parallel_orchestrator(self, ui_callback: Any = None) -> Any:
        """Build (once per run) the ParallelOrchestrator from this run's context.

        Requires the run's TaskIQClient (attached to the subagent manager via
        ``attach_task_client``). Returns None when no task client is available —
        parallel solving needs a running worker + Redis.
        """
        if getattr(self, "_parallel_orchestrator", None) is not None:
            return self._parallel_orchestrator
        mgr = self._subagent_manager
        task_client = getattr(mgr, "_task_client", None) if mgr is not None else None
        if task_client is None:
            return None
        from atria.core.parallel.tools import build_orchestrator, make_worktree_manager

        progress_cb = None
        if ui_callback is not None and hasattr(ui_callback, "on_solver_event"):
            progress_cb = lambda stage, data: ui_callback.on_solver_event(
                "parallel", stage, data
            )  # noqa: E731
        self._parallel_orchestrator = build_orchestrator(
            task_client=task_client,
            worktree_manager=make_worktree_manager(self._get_repo_dir()),
            config=self._app_config,
            llm_call=self.skill_ctx.llm_chat,
            progress_cb=progress_cb,
        )
        return self._parallel_orchestrator

    def _execute_solve_parallel(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Dispatch solve_parallel: fan out N worktree-isolated solvers for a task."""
        orch = self._get_parallel_orchestrator(ui_callback=getattr(context, "ui_callback", None))
        if orch is None:
            return {
                "success": False,
                "error": "Parallel solving unavailable (no task client). "
                "Requires a running TaskIQ worker + Redis.",
                "output": None,
            }
        repo_dir = self._get_repo_dir()
        _sess_mgr = getattr(context, "session_manager", None) if context else None
        _current = getattr(_sess_mgr, "current_session", None) if _sess_mgr else None
        owner_id = (getattr(_current, "owner_id", None) or "") if _current else ""
        session_id = str(getattr(_current, "session_id", "") or "") if _current else ""

        from atria.core.parallel.tools import execute_solve_parallel

        return execute_solve_parallel(arguments, orch, repo_dir, owner_id, session_id)

    def _execute_get_parallel_result(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Dispatch get_parallel_result: await solvers, judge candidates, apply winner."""
        orch = self._get_parallel_orchestrator(ui_callback=getattr(context, "ui_callback", None))
        if orch is None:
            return {
                "success": False,
                "error": "Parallel solving unavailable (no task client).",
                "output": None,
            }
        from atria.core.parallel.tools import execute_get_parallel_result

        return execute_get_parallel_result(arguments, orch)

    # ------------------------------------------------------------------
    # Divide-and-conquer tools (DeLM Phase 2c)
    # ------------------------------------------------------------------

    def _get_divide_orchestrator(self, ui_callback: Any = None) -> Any:
        """Build (once per run) the DivideOrchestrator from this run's context.

        Requires the run's TaskIQClient (attached to the subagent manager via
        ``attach_task_client``). Returns None when no task client is available —
        divide execution needs a running worker + Redis.
        """
        if getattr(self, "_divide_orchestrator", None) is not None:
            return self._divide_orchestrator
        mgr = self._subagent_manager
        task_client = getattr(mgr, "_task_client", None) if mgr is not None else None
        if task_client is None:
            return None

        from atria.core.divide.tools import build_divide_orchestrator
        from atria.core.modules.registry import resolve_modules_root

        progress_cb = None
        if ui_callback is not None and hasattr(ui_callback, "on_solver_event"):
            progress_cb = lambda stage, data: ui_callback.on_solver_event(
                "divide", stage, data
            )  # noqa: E731

        # Resolve owner/session from context — mirrors _execute_solve_parallel.
        # The orchestrator is built once; owner/session are baked in at build time.
        # (A per-call approach would require passing context here; the lazy-singleton
        # pattern matches the parallel implementation.)
        owner_id = ""
        session_id = ""

        self._divide_orchestrator = build_divide_orchestrator(
            task_client=task_client,
            config=self._app_config,
            llm_call=self.skill_ctx.llm_chat,
            modules_root=str(resolve_modules_root()),
            owner_id=owner_id,
            session_id=session_id,
            progress_cb=progress_cb,
        )
        return self._divide_orchestrator

    def _execute_divide_work(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Dispatch divide_work: decompose a request and fan sub-tasks out via the orchestrator."""
        orch = self._get_divide_orchestrator(ui_callback=getattr(context, "ui_callback", None))
        if orch is None:
            return {
                "success": False,
                "error": (
                    "Divide-work unavailable (no task client). "
                    "Requires a running TaskIQ worker + Redis."
                ),
                "output": None,
            }

        module_name = arguments.get("module") or ""
        module: Any = module_name  # fallback: pass name string to orchestrator
        module_skill = ""

        if module_name:
            try:
                from atria.core.modules.registry import get_registry

                reg = get_registry()
                mod_obj = reg.get(module_name)
                module = mod_obj
                module_skill = mod_obj.skill_md
            except KeyError:
                return {
                    "success": False,
                    "error": f"no such module {module_name!r}",
                    "output": None,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "success": False,
                    "error": f"module resolution failed: {exc}",
                    "output": None,
                }

        from atria.core.divide.tools import execute_divide_work

        return execute_divide_work(arguments, orch, module=module, module_skill=module_skill)

    def _execute_get_divide_result(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Dispatch get_divide_result: poll or await a divide_work job."""
        orch = self._get_divide_orchestrator(ui_callback=getattr(context, "ui_callback", None))
        if orch is None:
            return {
                "success": False,
                "error": "Divide-work unavailable (no task client).",
                "output": None,
            }

        from atria.core.divide.tools import execute_get_divide_result

        return execute_get_divide_result(arguments, orch)

    # ------------------------------------------------------------------
    # Unified solver tools (divide + parallel behind a ``strategy`` param)
    # ------------------------------------------------------------------

    def _strategy_map(self) -> dict[str, str]:
        """Lazy per-run map: job_id -> strategy, so get_solve_result can route."""
        mapping = getattr(self, "_solve_strategy_by_job", None)
        if mapping is None:
            mapping = {}
            self._solve_strategy_by_job = mapping
        return mapping

    def _execute_solve(self, arguments: dict[str, Any], context: Any = None) -> dict[str, Any]:
        """Dispatch a solve job by ``strategy`` (divide or parallel).

        'divide' decomposes a request into a DAG of interdependent sub-tasks and
        collects results. 'parallel' fans out N independent worktree-isolated
        solvers, judges candidates, and applies the winner's diff.
        """
        strategy = str(arguments.get("strategy") or "").strip().lower()
        if strategy not in ("divide", "parallel"):
            return {
                "success": False,
                "error": "strategy is required and must be 'divide' or 'parallel'.",
                "output": None,
            }
        if strategy == "parallel":
            result = self._execute_solve_parallel(arguments, context)
        else:
            result = self._execute_divide_work(arguments, context)
        job_id = result.get("job_id")
        if job_id:
            self._strategy_map()[job_id] = strategy
        return result

    def _execute_get_solve_result(
        self, arguments: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        """Collect a solve job's result, routing by strategy.

        Strategy is taken from the explicit ``strategy`` arg, else the per-run
        job_id->strategy map. As a cross-restart fallback it probes parallel
        (non-blocking) and otherwise routes to divide.
        """
        job_id = arguments.get("job_id", "")
        if not job_id:
            return {"success": False, "error": "job_id is required", "output": None}
        strategy = (
            str(arguments.get("strategy") or self._strategy_map().get(job_id) or "").strip().lower()
        )
        if strategy == "parallel":
            return self._execute_get_parallel_result(arguments, context)
        if strategy == "divide":
            return self._execute_get_divide_result(arguments, context)
        # Unknown (e.g. job created before a restart): probe parallel without
        # blocking; if it doesn't own the job, route to divide.
        probe = self._execute_get_parallel_result({**arguments, "block": False}, context)
        if probe.get("success"):
            return self._execute_get_parallel_result(arguments, context)
        return self._execute_get_divide_result(arguments, context)
