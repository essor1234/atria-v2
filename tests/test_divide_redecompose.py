"""Unit tests for divide-work stage-4 re-decomposition (DeLM W3)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from atria.core.divide.decompose import _validate_new, redecompose
from atria.core.divide.models import DivideJob, DivideTask
from atria.core.divide.orchestrator import DivideOrchestrator


# --------------------------------------------------------------------------- #
# _validate_new — fail-safe validation of a re-decomposition batch
# --------------------------------------------------------------------------- #
def test_validate_new_accepts_dep_on_existing_id():
    out = _validate_new(
        [{"id": "t9", "description": "do x", "depends_on": ["t1"]}], {"t1", "t2"}, 8
    )
    assert [(t.id, t.depends_on) for t in out] == [("t9", ["t1"])]


def test_validate_new_rejects_id_collision():
    assert _validate_new([{"id": "t1", "description": "x", "depends_on": []}], {"t1"}, 8) == []


def test_validate_new_rejects_unknown_dep():
    assert _validate_new([{"id": "t9", "description": "x", "depends_on": ["tZ"]}], {"t1"}, 8) == []


def test_validate_new_rejects_cycle_among_new():
    raw = [
        {"id": "a", "description": "x", "depends_on": ["b"]},
        {"id": "b", "description": "y", "depends_on": ["a"]},
    ]
    assert _validate_new(raw, set(), 8) == []


def test_validate_new_rejects_over_cap_and_empty():
    over = [{"id": f"n{i}", "description": "x", "depends_on": []} for i in range(9)]
    assert _validate_new(over, set(), 8) == []
    assert _validate_new([], set(), 8) == []


# --------------------------------------------------------------------------- #
# redecompose — DONE / array / fail-safe
# --------------------------------------------------------------------------- #
def test_redecompose_done_returns_empty():
    assert redecompose("req", "skill", "t1[done]", "", {"t1"}, lambda s, u: "DONE", 8) == []


def test_redecompose_parses_new_tasks():
    out = redecompose(
        "req", "skill", "t1[done]", "digest", {"t1"},
        lambda s, u: '[{"id":"t2","description":"more","depends_on":["t1"]}]', 8,
    )
    assert [(t.id, t.depends_on) for t in out] == [("t2", ["t1"])]


def test_redecompose_tolerates_bare_object():
    # Models often emit a single task as a bare object, not an array (seen in real e2e).
    out = redecompose(
        "req", "skill", "t1[done]", "digest", {"t1"},
        lambda s, u: '{"id":"t2","description":"write the missing test","depends_on":["t1"]}',
        8,
    )
    assert [(t.id, t.depends_on) for t in out] == [("t2", ["t1"])]


def test_redecompose_unparseable_returns_empty():
    assert redecompose("r", "s", "c", "d", set(), lambda s, u: "maybe later?", 8) == []


def test_redecompose_llm_error_is_failsafe():
    def boom(s, u):
        raise RuntimeError("verifier down")

    assert redecompose("r", "s", "c", "d", set(), boom, 8) == []


# --------------------------------------------------------------------------- #
# Orchestrator loop — new tasks join the DAG and get scheduled; rounds are bounded
# --------------------------------------------------------------------------- #
class _FakeJobStore:
    def __init__(self):
        self.saved = {}

    async def save(self, job_id, record, ttl=0):
        self.saved[job_id] = record

    async def load(self, job_id):
        return self.saved.get(job_id)


def _orch(llm, cfg, enqueued, awaited):
    async def enqueue_worker(payload):
        tid = f"kiq-{len(enqueued)}"
        enqueued.append(payload)
        return tid

    async def await_worker(ids):
        # Complete the first in-flight worker successfully.
        tid = ids[0]
        awaited.append(tid)
        return tid, {"status": "done", "output": f"result-of-{tid}"}

    return DivideOrchestrator(
        job_store=_FakeJobStore(),
        redis_client=None,  # _read_digest catches and returns "" -> exercised
        llm_call=llm,
        config=cfg,
        run_async=lambda coro: asyncio.get_event_loop().run_until_complete(coro),
        enqueue_worker=enqueue_worker,
        await_worker=await_worker,
        modules_root="/tmp",
        owner_id="o",
        session_id="s",
    )


def test_orchestrator_runs_one_redecompose_round_then_done():
    cfg = SimpleNamespace(
        max_tasks=8, max_parallel=3, max_redecompose_rounds=1, pjob_ttl=3600
    )
    calls = {"n": 0}

    def llm(system, user):
        # First call = initial decompose; second = redecompose (one new task); then DONE.
        calls["n"] += 1
        if "split a user's request" in system.lower() or calls["n"] == 1:
            return '[{"id":"t1","description":"first","depends_on":[]}]'
        if calls["n"] == 2:
            return '[{"id":"t2","description":"followup","depends_on":["t1"]}]'
        return "DONE"

    enqueued, awaited = [], []
    orch = _orch(llm, cfg, enqueued, awaited)
    job_id = asyncio.run(orch.start_async("do a thing", "module-skill", "module-skill"))

    rec = orch._js.saved[job_id]
    job = DivideJob(**rec)
    ids = [t.id for t in job.tasks]
    assert ids == ["t1", "t2"], f"re-decomposition task not added: {ids}"
    assert all(t.status == "done" for t in job.tasks)
    assert job.status == "done"
    # t1 enqueued in round 1, t2 enqueued in round 2 -> two enqueues total.
    assert len(enqueued) == 2


def test_orchestrator_redecompose_disabled_when_rounds_zero():
    cfg = SimpleNamespace(
        max_tasks=8, max_parallel=3, max_redecompose_rounds=0, pjob_ttl=3600
    )

    def llm(system, user):
        return '[{"id":"t1","description":"only","depends_on":[]}]'

    enqueued, awaited = [], []
    orch = _orch(llm, cfg, enqueued, awaited)
    job_id = asyncio.run(orch.start_async("do a thing", "skill", "skill"))
    job = DivideJob(**orch._js.saved[job_id])
    assert [t.id for t in job.tasks] == ["t1"]
    assert len(enqueued) == 1  # no second round


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
