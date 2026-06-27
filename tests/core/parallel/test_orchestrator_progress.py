"""Tests for ParallelOrchestrator progress callback (_emit + started event)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from atria.core.parallel.orchestrator import ParallelOrchestrator


def _make_orchestrator(progress_cb=None) -> ParallelOrchestrator:
    """Build a ParallelOrchestrator with all external deps mocked."""
    task_client = MagicMock()
    worktree_manager = MagicMock()
    job_store = MagicMock()
    redis_client = MagicMock()
    llm_call = MagicMock(return_value="verdict")
    config = SimpleNamespace(default_solvers=2, max_solvers=8, pjob_ttl=3600)

    loop = asyncio.new_event_loop()

    def run_async(coro):
        return loop.run_until_complete(coro)

    return ParallelOrchestrator(
        task_client=task_client,
        worktree_manager=worktree_manager,
        job_store=job_store,
        redis_client=redis_client,
        llm_call=llm_call,
        config=config,
        run_async=run_async,
        progress_cb=progress_cb,
    )


class TestEmitSwallowsExceptions:
    def test_raising_callback_does_not_propagate(self):
        def bad_cb(stage, data):
            raise RuntimeError("explode")

        orch = _make_orchestrator(progress_cb=bad_cb)
        # Must not raise
        orch._emit("started", {})

    def test_none_callback_is_noop(self):
        orch = _make_orchestrator(progress_cb=None)
        orch._emit("started", {"some": "data"})  # no error


class TestStartedEvent:
    def test_started_event_emitted(self, monkeypatch):
        events: list[tuple[str, dict]] = []

        def cb(stage, data):
            events.append((stage, data))

        orch = _make_orchestrator(progress_cb=cb)

        fake_wt = SimpleNamespace(branch="worktree-abc", path="/tmp/wt-abc")
        orch._wm.create.return_value = fake_wt
        orch._tc.enqueue.return_value = "task-001"

        async def fake_save(*args, **kwargs):
            return None

        orch._js.save = MagicMock(return_value=fake_save())

        monkeypatch.setattr(
            "atria.core.parallel.orchestrator.snapshot_worktree",
            lambda repo_dir: "fake-base-ref",
        )

        # Patch SubagentTaskPayload import inside start()
        fake_payload_cls = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"atria.core.tasks.payload": MagicMock(SubagentTaskPayload=fake_payload_cls)},
        ):
            job_id = orch.start(
                task="fix the bug",
                n=2,
                repo_dir="/repo",
                owner_id="owner-1",
                session_id="sess-1",
            )

        assert len(events) == 1
        stage, data = events[0]
        assert stage == "started"
        assert data["job_id"] == job_id
        assert data["n"] == 2
        assert data["task"] == "fix the bug"
        assert isinstance(data["worktree_names"], list)

    def test_no_callback_start_returns_job_id(self, monkeypatch):
        orch = _make_orchestrator(progress_cb=None)

        fake_wt = SimpleNamespace(branch="worktree-xyz", path="/tmp/wt-xyz")
        orch._wm.create.return_value = fake_wt
        orch._tc.enqueue.return_value = "task-002"

        async def fake_save(*args, **kwargs):
            return None

        orch._js.save = MagicMock(return_value=fake_save())

        monkeypatch.setattr(
            "atria.core.parallel.orchestrator.snapshot_worktree",
            lambda repo_dir: "base-ref-2",
        )

        fake_payload_cls = MagicMock(return_value=MagicMock())
        with patch.dict(
            "sys.modules",
            {"atria.core.tasks.payload": MagicMock(SubagentTaskPayload=fake_payload_cls)},
        ):
            job_id = orch.start(
                task="another task",
                n=2,
                repo_dir="/repo",
                owner_id="owner-2",
                session_id="sess-2",
            )

        assert isinstance(job_id, str)
        assert len(job_id) == 12
