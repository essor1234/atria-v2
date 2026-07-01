"""Unit tests for staggered solver waves (DeLM W2) in ParallelOrchestrator."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from atria.core.parallel import orchestrator as orch_mod
from atria.core.parallel.orchestrator import ParallelOrchestrator, plan_waves


# --------------------------------------------------------------------------- #
# plan_waves
# --------------------------------------------------------------------------- #
def test_plan_waves_even_and_uneven():
    assert plan_waves(4, 2) == [2, 2]
    assert plan_waves(3, 2) == [2, 1]
    assert plan_waves(5, 2) == [3, 2]
    assert plan_waves(2, 2) == [1, 1]
    assert plan_waves(2, 3) == [1, 1]   # waves clamped to n
    assert plan_waves(3, 1) == [3]      # single fan-out
    assert sum(plan_waves(7, 3)) == 7


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeTC:
    def __init__(self, log):
        self.log = log
        self._i = 0

    def startup(self):
        pass

    def enqueue(self, payload):
        tid = f"t{self._i}"
        self._i += 1
        self.log.append(("enqueue", tid, payload.thread_id))
        return tid

    def await_result(self, tid, block=True, timeout_ms=30000):
        self.log.append(("await", tid))
        return {"status": "done", "success": True}


class _FakeWM:
    def __init__(self):
        self._i = 0
        self.removed = []

    def create(self, base_branch=None):
        wt = SimpleNamespace(branch=f"worktree-w{self._i}", path=f"/wt/w{self._i}")
        self._i += 1
        return wt

    def remove(self, name, force=False):
        self.removed.append(name)


class _FakeJS:
    """In-memory async job store; json round-trips to mimic redis serialization."""

    def __init__(self):
        self.store = {}

    async def save(self, job_id, record, ttl):
        self.store[job_id] = json.loads(json.dumps(record))

    async def load(self, job_id):
        rec = self.store.get(job_id)
        return json.loads(json.dumps(rec)) if rec is not None else None

    async def delete(self, job_id):
        self.store.pop(job_id, None)


def _build(monkeypatch, log, *, waves=2, progress=None):
    monkeypatch.setattr(orch_mod, "snapshot_worktree", lambda repo: "base-ref")
    monkeypatch.setattr(
        orch_mod, "extract_candidate",
        lambda path, base, notes, tid: SimpleNamespace(
            thread_id=tid, diff=f"diff-{tid}", patch_summary=f"ps-{tid}", ok=True
        ),
    )
    monkeypatch.setattr(
        orch_mod, "judge_candidates",
        lambda task, cands, llm: SimpleNamespace(
            winner_index=0 if cands else -1, reasoning="picked first"
        ),
    )
    monkeypatch.setattr(
        orch_mod, "apply_diff",
        lambda repo, diff: SimpleNamespace(ok=True, conflicted_files=[]),
    )
    loop = asyncio.new_event_loop()
    cfg = SimpleNamespace(default_solvers=2, max_solvers=8, pjob_ttl=3600, waves=waves)
    o = ParallelOrchestrator(
        task_client=_FakeTC(log),
        worktree_manager=_FakeWM(),
        job_store=_FakeJS(),
        redis_client=object(),
        llm_call=lambda s, u: "v",
        config=cfg,
        run_async=lambda coro: loop.run_until_complete(coro),
        progress_cb=progress,
    )
    o._read_notes = lambda bb_id: []  # bypass redis blackboard read
    return o


# --------------------------------------------------------------------------- #
# start enqueues only the first wave
# --------------------------------------------------------------------------- #
def test_start_enqueues_only_first_wave(monkeypatch):
    log = []
    o = _build(monkeypatch, log, waves=2)
    job_id = o.start("fix bug", n=4, repo_dir="/repo", owner_id="o", session_id="s")
    enqueues = [e for e in log if e[0] == "enqueue"]
    assert len(enqueues) == 2, "wave 1 of [2,2] should enqueue exactly 2 solvers"
    rec = o._js.store[job_id]
    assert rec["wave_sizes"] == [2, 2]
    assert rec["wave_index"] == 0
    assert len(rec["solvers"]) == 2
    assert len(rec["inflight"]) == 2


# --------------------------------------------------------------------------- #
# THE KEY W2 PROPERTY: wave 2 is enqueued only AFTER wave 1 has been awaited,
# so wave-2 solvers build their prompts with wave-1's verified notes available.
# --------------------------------------------------------------------------- #
def test_collect_advances_waves_with_shared_ordering(monkeypatch):
    log = []
    o = _build(monkeypatch, log, waves=2)
    job_id = o.start("fix bug", n=4, repo_dir="/repo", owner_id="o", session_id="s")
    result = o.collect(job_id, block=True)

    # All 4 solvers enqueued across 2 waves.
    enqueue_order = [e for e in log if e[0] == "enqueue"]
    assert len(enqueue_order) == 4
    # The 3rd enqueue (first of wave 2) must come AFTER at least one await — i.e. wave 2
    # starts only once wave 1's results (and their blackboard notes) exist.
    idx_third_enqueue = [i for i, e in enumerate(log) if e[0] == "enqueue"][2]
    awaits_before = [i for i, e in enumerate(log) if e[0] == "await" and i < idx_third_enqueue]
    assert awaits_before, "wave 2 enqueued before any wave-1 await — sharing not realized"

    assert result["status"] == "done"
    assert result["applied"] is True
    assert result["winner_thread"] == 0
    assert result["waves"] == 2
    assert len(result["candidates"]) == 4  # judged across every wave
    # All worktrees cleaned up.
    assert len(o._wm.removed) == 4


def test_waves_event_emitted_between_waves(monkeypatch):
    events = []
    log = []
    o = _build(monkeypatch, log, waves=2, progress=lambda s, d: events.append((s, d)))
    job_id = o.start("t", n=4, repo_dir="/r", owner_id="o", session_id="s")
    o.collect(job_id, block=True)
    stages = [s for s, _ in events]
    assert "started" in stages and "wave" in stages and "done" in stages


# --------------------------------------------------------------------------- #
# waves=1 restores single simultaneous fan-out
# --------------------------------------------------------------------------- #
def test_waves_one_is_single_fanout(monkeypatch):
    log = []
    o = _build(monkeypatch, log, waves=1)
    job_id = o.start("t", n=3, repo_dir="/r", owner_id="o", session_id="s")
    # All 3 enqueued up front (single wave).
    assert len([e for e in log if e[0] == "enqueue"]) == 3
    result = o.collect(job_id, block=True)
    assert result["waves"] == 1
    assert len(result["candidates"]) == 3


# --------------------------------------------------------------------------- #
# non-blocking poll advances one wave per call
# --------------------------------------------------------------------------- #
def test_nonblocking_collect_returns_running_between_waves(monkeypatch):
    log = []
    o = _build(monkeypatch, log, waves=2)
    job_id = o.start("t", n=4, repo_dir="/r", owner_id="o", session_id="s")
    first = o.collect(job_id, block=False)
    assert first["status"] == "running"
    assert first["wave"] == 2  # advanced to wave 2, now in flight
    second = o.collect(job_id, block=False)
    assert second["status"] == "done"
    assert len(second["candidates"]) == 4


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
