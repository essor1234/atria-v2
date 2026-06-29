# DeLM Parallel Solvers + Judge (Phase 2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `solve_parallel(task, n)` tool that fans out N autonomous background subagents — each in its own git worktree (off a snapshot of the current incl-uncommitted state), each with the Phase 2a blackboard attached — and a `get_parallel_result(job_id)` that awaits them, extracts candidates (worktree diff + verified PATCH_SUMMARY), runs an LLM judge, and applies the winner's diff to the user's workspace.

**Architecture:** A thin `atria/core/parallel/` orchestration layer (snapshot / job_store / candidate / judge / apply / orchestrator) on top of reused pieces: `WorktreeManager`, the Sub-project 1 TaskIQ substrate (extended payload), and the Phase 2a blackboard. Two tools mirror Sub-project 1's `spawn_subagent`/`get_subagent_output`.

**Tech Stack:** Python 3.11+, git CLI via subprocess, `redis.asyncio`, the project's `http_client.post_json` LLM helper, Pydantic v2.

## ⚠️ NO TESTS (explicit user decision)

Per the user's explicit request, this phase has **NO formal unit tests and NO TDD steps**. Each task is direct implementation followed by a quick `python -c` import/smoke check, then a commit. A single final task does a real manual smoke run. This OVERRIDES the project's usual testing rule for Phase 2b only.

Two safety rails are NON-NEGOTIABLE (they are recovery, not tests) and MUST be implemented as specified: `apply_diff` uses `git apply --3way` (conflicts surface, never force-revert); the working-tree snapshot ref is RETAINED until the agent confirms (cleanup removes worktrees but the spec's recovery posture means we do not destroy the user's ability to recover — see Task 2 + Task 8).

## Dependencies / order

- **Phase 2b REQUIRES Phase 2a to be implemented first** (`atria/core/blackboard/*`: `Blackboard`, `BlackboardHandle`, `PATCH_SUMMARY` notes, `ToolExecutionContext.blackboard`, the `NOTE` tool). Do not start Phase 2b until Phase 2a is merged.
- Also depends on Sub-project 1 (shipped): `TaskIQClient`, `SubagentTaskPayload`, the worker run path, `atria/core/git/worktree.py WorktreeManager`.

## Global Constraints

- Line length 100 (Black + Ruff). Type hints on public APIs. Google-style docstrings.
- No new runtime deps (git CLI, `redis.asyncio`, the LLM `http_client` already present).
- Redis client is INJECTABLE and CALLER-OWNED (mirror `atria/core/tasks/meta.py`). Key prefixes: job store `atria:pjob:`.
- `n` clamped to `[2, max_solvers]` (config, default max 5, default 3).
- Run smoke checks with `.venv/bin/python` / `.venv/bin/pytest` (NOT `uv run`). Lint new files with `uvx ruff check`.
- `apply_diff` MUST use `git apply --3way`. The snapshot ref MUST be retained until the agent confirms (do NOT discard it inside `collect`'s cleanup — only remove worktrees + job record; leave snapshot recovery to the caller/agent).
- `docs/` is gitignored → `git add -f` for any docs.
- Conventional Commit messages; NO `Co-Authored-By: Claude` trailer.

---

### Task 1: Config + payload extension

**Files:**
- Modify: `atria/models/config.py` (add `ParallelConfig`, attach to `AppConfig`)
- Modify: `atria/core/tasks/payload.py` (add `blackboard_task_id`, `thread_id`)

**Interfaces:**
- Produces: `ParallelConfig(max_solvers=5, default_solvers=3, solver_start_stagger_seconds=0, pjob_ttl=3600, redis_url="redis://localhost:6379/0")`; `AppConfig.parallel`. `SubagentTaskPayload.blackboard_task_id: str | None = None`, `SubagentTaskPayload.thread_id: int = 0`.

- [ ] **Step 1: Add `ParallelConfig`**

In `atria/models/config.py`, below `BlackboardConfig` (added in Phase 2a) / `TasksConfig`:

```python
class ParallelConfig(BaseModel):
    """Parallel multi-solver (DeLM Phase 2b) settings."""

    max_solvers: int = 5
    default_solvers: int = 3
    solver_start_stagger_seconds: float = 0.0
    pjob_ttl: int = 3600
    redis_url: str = "redis://localhost:6379/0"
```

In `AppConfig`, alongside `tasks`/`blackboard`:

```python
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
```

- [ ] **Step 2: Extend the payload**

In `atria/core/tasks/payload.py`, add two fields to `SubagentTaskPayload` (after `config_snapshot` or anywhere in the model):

```python
    blackboard_task_id: str | None = None
    thread_id: int = 0
```

- [ ] **Step 3: Smoke check**

Run:
```bash
ENVIRONMENT=pytest .venv/bin/python -c "
from atria.models.config import ParallelConfig, AppConfig
from atria.core.tasks.payload import SubagentTaskPayload
assert ParallelConfig().max_solvers == 5
p = SubagentTaskPayload(session_id='s', owner_id='o', subagent_type='solver', prompt='x', working_dir='/tmp', config_snapshot={}, blackboard_task_id='bb1', thread_id=2)
assert p.model_dump()['thread_id'] == 2 and p.blackboard_task_id == 'bb1'
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add atria/models/config.py atria/core/tasks/payload.py
git commit -m "feat(parallel): ParallelConfig + payload blackboard_task_id/thread_id"
```

---

### Task 2: Snapshot helper

**Files:**
- Create: `atria/core/parallel/__init__.py`
- Create: `atria/core/parallel/snapshot.py`

**Interfaces:**
- Produces: `snapshot_worktree(repo_dir: str) -> str` (a commit-ish that includes committed + uncommitted state); `discard_snapshot(repo_dir: str, ref: str) -> None`.

- [ ] **Step 1: Implement**

```python
# atria/core/parallel/__init__.py
"""Parallel multi-solver orchestration (DeLM Phase 2b)."""
```

```python
# atria/core/parallel/snapshot.py
"""Snapshot the working tree (incl. uncommitted changes) as a base commit for worktrees."""
from __future__ import annotations

import subprocess


def _git(repo_dir: str, *args: str) -> tuple[int, str, str]:
    p = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def snapshot_worktree(repo_dir: str) -> str:
    """Return a commit-ish capturing committed + uncommitted state.

    Uses `git stash create` when the tree is dirty (this writes a commit object WITHOUT
    touching the working tree or stash list), else HEAD. The returned ref is what solver
    worktrees fork from. It is a dangling commit; retain it for recovery until confirmed.
    """
    code, out, _ = _git(repo_dir, "stash", "create")
    if code == 0 and out:
        return out  # dirty: a new commit including tracked uncommitted changes
    code, head, _ = _git(repo_dir, "rev-parse", "HEAD")
    return head if code == 0 else "HEAD"


def discard_snapshot(repo_dir: str, ref: str) -> None:
    """Best-effort: drop a snapshot commit object (only call once recovery is no longer needed)."""
    # A `git stash create` commit is dangling; gc will reclaim it. Nothing to force-delete
    # safely without risking real refs, so this is intentionally a no-op placeholder that
    # documents intent. Retention-until-confirmed is the safety rail.
    return None
```

(Note: `discard_snapshot` is intentionally a no-op — the snapshot is a dangling commit reclaimed by git gc; we never force-delete it, honoring "retain until confirmed".)

- [ ] **Step 2: Smoke check**

Run:
```bash
.venv/bin/python -c "
import subprocess, tempfile, os
from atria.core.parallel.snapshot import snapshot_worktree
d = tempfile.mkdtemp()
subprocess.run(['git','init','-q'], cwd=d); subprocess.run(['git','config','user.email','a@b.c'], cwd=d); subprocess.run(['git','config','user.name','t'], cwd=d)
open(os.path.join(d,'f.txt'),'w').write('hi'); subprocess.run(['git','add','.'], cwd=d); subprocess.run(['git','commit','-qm','init'], cwd=d)
clean = snapshot_worktree(d)
open(os.path.join(d,'f.txt'),'w').write('changed'); 
dirty = snapshot_worktree(d)
assert clean and dirty and clean != dirty, (clean, dirty)
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add atria/core/parallel/__init__.py atria/core/parallel/snapshot.py
git commit -m "feat(parallel): working-tree snapshot helper"
```

---

### Task 3: Job store (Redis)

**Files:**
- Create: `atria/core/parallel/job_store.py`

**Interfaces:**
- Produces: `JobStore(redis)` with async `save(job_id: str, record: dict, ttl: int) -> None`, `load(job_id: str) -> dict | None`, `delete(job_id: str) -> None`. Key `atria:pjob:{job_id}`.

- [ ] **Step 1: Implement (mirror `atria/core/tasks/meta.py` conventions)**

```python
# atria/core/parallel/job_store.py
"""Redis-backed record for an in-flight parallel-solve job. Caller owns the redis client."""
from __future__ import annotations

import json

_PREFIX = "atria:pjob:"


class JobStore:
    """CRUD for parallel-solve job records keyed atria:pjob:{job_id}."""

    def __init__(self, redis: object) -> None:
        self._redis = redis

    async def save(self, job_id: str, record: dict, ttl: int) -> None:
        await self._redis.set(_PREFIX + job_id, json.dumps(record), ex=ttl)  # type: ignore[attr-defined]

    async def load(self, job_id: str) -> dict | None:
        raw = await self._redis.get(_PREFIX + job_id)  # type: ignore[attr-defined]
        if raw is None:
            return None
        s = raw.decode() if isinstance(raw, bytes) else raw
        return json.loads(s)

    async def delete(self, job_id: str) -> None:
        await self._redis.delete(_PREFIX + job_id)  # type: ignore[attr-defined]
```

- [ ] **Step 2: Smoke check (fakeredis)**

Run:
```bash
.venv/bin/python -c "
import asyncio
from fakeredis import aioredis as fr
from atria.core.parallel.job_store import JobStore
async def main():
    js = JobStore(fr.FakeRedis())
    await js.save('j1', {'n': 3}, ttl=60)
    assert (await js.load('j1'))['n'] == 3
    await js.delete('j1'); assert await js.load('j1') is None
    print('ok')
asyncio.run(main())
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add atria/core/parallel/job_store.py
git commit -m "feat(parallel): redis job store"
```

---

### Task 4: Candidate extraction

**Files:**
- Create: `atria/core/parallel/candidate.py`

**Interfaces:**
- Consumes: a blackboard with `read_all()`-style access to notes (Phase 2a `Blackboard`/`BlackboardStore`).
- Produces: `Candidate` dataclass (`thread_id: int`, `diff: str`, `patch_summary: str`, `ok: bool`); `extract_candidate(worktree_path, base_ref, notes, thread_id) -> Candidate` where `notes` is a list of note dicts/objects with `type`/`content`/`thread_id`.

- [ ] **Step 1: Implement**

```python
# atria/core/parallel/candidate.py
"""Extract one solver's candidate solution: its worktree diff + verified PATCH_SUMMARY."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class Candidate:
    """A solver's candidate: the diff its worktree produced + its PATCH_SUMMARY note."""

    thread_id: int
    diff: str
    patch_summary: str
    ok: bool


def _git_diff(worktree_path: str, base_ref: str) -> str:
    p = subprocess.run(
        ["git", "diff", base_ref], cwd=worktree_path, capture_output=True, text=True, timeout=60
    )
    return p.stdout if p.returncode == 0 else ""


def extract_candidate(worktree_path: str, base_ref: str, notes: list, thread_id: int) -> Candidate:
    """Build a Candidate from a solver's worktree diff and its latest PATCH_SUMMARY note.

    Args:
        worktree_path: The solver's worktree directory.
        base_ref: The snapshot commit the worktrees forked from.
        notes: All blackboard notes (each has .type/.content/.thread_id or dict keys).
        thread_id: Which solver this candidate is for.
    """
    diff = _git_diff(worktree_path, base_ref)

    def _f(n, k):
        return getattr(n, k, None) if not isinstance(n, dict) else n.get(k)

    summaries = [
        _f(n, "content")
        for n in notes
        if _f(n, "type") == "PATCH_SUMMARY" and int(_f(n, "thread_id") or 0) == thread_id
    ]
    patch_summary = summaries[-1] if summaries else ""
    ok = bool(diff.strip()) and bool(patch_summary)
    return Candidate(thread_id=thread_id, diff=diff, patch_summary=patch_summary, ok=ok)
```

- [ ] **Step 2: Smoke check**

Run:
```bash
.venv/bin/python -c "
import subprocess, tempfile, os
from atria.core.parallel.candidate import extract_candidate
d = tempfile.mkdtemp()
subprocess.run(['git','init','-q'], cwd=d); subprocess.run(['git','config','user.email','a@b.c'], cwd=d); subprocess.run(['git','config','user.name','t'], cwd=d)
open(os.path.join(d,'f.txt'),'w').write('a\n'); subprocess.run(['git','add','.'], cwd=d); subprocess.run(['git','commit','-qm','init'], cwd=d)
base = subprocess.run(['git','rev-parse','HEAD'], cwd=d, capture_output=True, text=True).stdout.strip()
open(os.path.join(d,'f.txt'),'w').write('b\n')
notes = [{'type':'PATCH_SUMMARY','content':'files=f.txt | idea=x | evidence=ran t PASSED | risk=n','thread_id':0}]
c = extract_candidate(d, base, notes, 0)
assert c.ok and 'f.txt' in c.diff and 'evidence' in c.patch_summary, c
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add atria/core/parallel/candidate.py
git commit -m "feat(parallel): candidate extraction (diff + PATCH_SUMMARY)"
```

---

### Task 5: LLM judge

**Files:**
- Create: `atria/core/parallel/judge.py`

**Interfaces:**
- Consumes: `Candidate` (Task 4); the project's LLM call mechanism.
- Produces: `JudgeResult` dataclass (`winner_index: int`, `reasoning: str`); `judge_candidates(task: str, candidates: list[Candidate], llm_call) -> JudgeResult`. `winner_index == -1` means "none acceptable". `llm_call` is an injected callable `(system: str, user: str) -> str` so the LLM transport is pluggable (and trivially stubbable in the smoke check).

- [ ] **Step 1: Inspect the LLM transport**

Run: `sed -n '172,230p' atria/core/agents/components/api/http_client.py` and `sed -n '80,95p' atria/core/context_engineering/tools/registry.py`
Pick the simplest one-shot chat-completion path (the `client.chat.completions.create(...)` at registry.py:86 is a direct single call). In Task 9 the orchestrator will pass a concrete `llm_call` built from that; here `judge_candidates` takes `llm_call` as a parameter so the judge itself has no transport dependency.

- [ ] **Step 2: Implement**

```python
# atria/core/parallel/judge.py
"""LLM judge: pick the best of N candidate solutions by diff + verified PATCH_SUMMARY."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from atria.core.parallel.candidate import Candidate

_SYSTEM = (
    "You are selecting the single best candidate code change for a task. Each candidate has a "
    "unified diff and a PATCH_SUMMARY whose evidence= field reports a verification the solver "
    "actually ran. Prefer the candidate with the strongest real evidence, the smallest correct "
    "change, and the lowest stated risk. Reply ONLY with JSON: "
    '{"winner_index": <int>, "reasoning": "<one sentence>"}. Use winner_index -1 if none are '
    "acceptable (empty diff, no real evidence)."
)


def _build_user(task: str, candidates: list[Candidate]) -> str:
    blocks = []
    for i, c in enumerate(candidates):
        blocks.append(
            f"### Candidate {i} (thread {c.thread_id})\n"
            f"PATCH_SUMMARY: {c.patch_summary or '(none)'}\n"
            f"DIFF:\n{c.diff[:6000]}"
        )
    return f"TASK:\n{task}\n\n" + "\n\n".join(blocks)


@dataclass
class JudgeResult:
    """Outcome of judging: winning candidate index (or -1) + a one-line reason."""

    winner_index: int
    reasoning: str


def judge_candidates(
    task: str, candidates: list[Candidate], llm_call: Callable[[str, str], str]
) -> JudgeResult:
    """Ask the LLM to pick the best candidate. Returns winner_index -1 when none qualify.

    Args:
        task: The original task description.
        candidates: The extracted candidates (already filtered to finished solvers).
        llm_call: Callable (system, user) -> assistant_text.
    """
    usable = [c for c in candidates if c.ok]
    if not usable:
        return JudgeResult(winner_index=-1, reasoning="no candidate with a diff and real evidence")
    raw = llm_call(_SYSTEM, _build_user(task, candidates))
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return JudgeResult(winner_index=-1, reasoning="judge returned no parseable JSON")
    try:
        data = json.loads(m.group(0))
        idx = int(data.get("winner_index", -1))
        reason = str(data.get("reasoning", ""))
    except (ValueError, TypeError):
        return JudgeResult(winner_index=-1, reasoning="judge JSON invalid")
    if idx < 0 or idx >= len(candidates) or not candidates[idx].ok:
        return JudgeResult(winner_index=-1, reasoning=reason or "judge chose an invalid candidate")
    return JudgeResult(winner_index=idx, reasoning=reason)
```

- [ ] **Step 3: Smoke check (stub llm_call)**

Run:
```bash
.venv/bin/python -c "
from atria.core.parallel.candidate import Candidate
from atria.core.parallel.judge import judge_candidates
cands = [Candidate(0,'diff a','files=a | idea=x | evidence=ran PASSED | risk=n',True),
         Candidate(1,'diff b','files=b | idea=y | evidence=ran PASSED | risk=n',True)]
r = judge_candidates('do it', cands, lambda s,u: '{\"winner_index\": 1, \"reasoning\": \"smaller\"}')
assert r.winner_index == 1, r
r2 = judge_candidates('do it', [Candidate(0,'','',False)], lambda s,u: 'x')
assert r2.winner_index == -1, r2
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add atria/core/parallel/judge.py
git commit -m "feat(parallel): LLM judge over candidate diffs + evidence"
```

---

### Task 6: Apply winner (git apply --3way)

**Files:**
- Create: `atria/core/parallel/apply.py`

**Interfaces:**
- Produces: `ApplyResult` dataclass (`ok: bool`, `conflicted_files: list[str]`); `apply_diff(repo_dir: str, diff: str) -> ApplyResult`. MUST use `git apply --3way`.

- [ ] **Step 1: Implement**

```python
# atria/core/parallel/apply.py
"""Apply the winning candidate's diff to the user's workspace with 3-way merge."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field


@dataclass
class ApplyResult:
    """Outcome of applying a diff: ok plus any files left with conflict markers."""

    ok: bool
    conflicted_files: list[str] = field(default_factory=list)


def apply_diff(repo_dir: str, diff: str) -> ApplyResult:
    """Apply `diff` onto repo_dir with `git apply --3way`.

    On conflicts, markers are left in place (not reverted) and the conflicting files are
    reported. The caller retains the snapshot ref for recovery.
    """
    if not diff.strip():
        return ApplyResult(ok=False)
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
        patch_path = f.name
    p = subprocess.run(
        ["git", "apply", "--3way", patch_path],
        cwd=repo_dir, capture_output=True, text=True, timeout=60,
    )
    if p.returncode == 0:
        return ApplyResult(ok=True)
    # --3way leaves conflict markers and lists files in stderr ("U <file>" / "CONFLICT").
    conflicted: list[str] = []
    for line in (p.stderr or "").splitlines():
        s = line.strip()
        if s.startswith("U ") or "with conflicts" in s.lower():
            parts = s.split()
            if len(parts) >= 2:
                conflicted.append(parts[-1])
    return ApplyResult(ok=False, conflicted_files=conflicted)
```

- [ ] **Step 2: Smoke check**

Run:
```bash
.venv/bin/python -c "
import subprocess, tempfile, os
from atria.core.parallel.apply import apply_diff
d = tempfile.mkdtemp()
subprocess.run(['git','init','-q'], cwd=d); subprocess.run(['git','config','user.email','a@b.c'], cwd=d); subprocess.run(['git','config','user.name','t'], cwd=d)
open(os.path.join(d,'f.txt'),'w').write('a\n'); subprocess.run(['git','add','.'], cwd=d); subprocess.run(['git','commit','-qm','init'], cwd=d)
base = subprocess.run(['git','rev-parse','HEAD'], cwd=d, capture_output=True, text=True).stdout.strip()
open(os.path.join(d,'f.txt'),'w').write('b\n')
diff = subprocess.run(['git','diff'], cwd=d, capture_output=True, text=True).stdout
subprocess.run(['git','checkout','--','f.txt'], cwd=d)  # revert, then apply via our fn
r = apply_diff(d, diff)
assert r.ok and open(os.path.join(d,'f.txt')).read() == 'b\n', r
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add atria/core/parallel/apply.py
git commit -m "feat(parallel): apply winner diff with git apply --3way"
```

---

### Task 7: Worker blackboard attach

**Files:**
- Modify: the worker run path (`atria/core/tasks/tasks.py` `_run_subagent_sync`, and/or `atria/core/agents/deps_builder.py`)

**Interfaces:**
- Consumes: `SubagentTaskPayload.blackboard_task_id`/`thread_id` (Task 1); Phase 2a `Blackboard`/`BlackboardHandle`/`BlackboardStore` + `ToolExecutionContext.blackboard`.
- Produces: when `payload.blackboard_task_id` is set, the solver's run has a `BlackboardHandle` attached so the `NOTE` tool + "Shared Lessons" injection are active for that solver (`thread_id` = `payload.thread_id`).

- [ ] **Step 1: Inspect the attach point**

Run: `sed -n '1,60p' atria/core/tasks/tasks.py` and `grep -rn "ToolExecutionContext(\|\.blackboard" atria/core/ | head`
Phase 2a Task 8 added `ToolExecutionContext.blackboard`. Find where the worker's subagent run builds its tool-execution context (via `execute_subagent` / `build_runtime_and_deps`). The blackboard handle must be attached there for the run.

- [ ] **Step 2: Implement the attach**

In `_run_subagent_sync` (worker), when `payload.blackboard_task_id` is set, construct the handle and attach it. Concretely (adjust import paths / construction to Phase 2a's actual API):

```python
        blackboard_handle = None
        if payload.blackboard_task_id:
            import redis.asyncio as aioredis
            from atria.core.blackboard.blackboard import Blackboard, BlackboardHandle
            from atria.core.blackboard.store import BlackboardStore

            # Build against the configured blackboard Redis (caller-owned client; the handle's
            # background loop owns its lifecycle for this worker run).
            redis_url = (runtime_suite_config_redis_url_or_default)  # from config; default redis://localhost:6379/0
            client = aioredis.from_url(redis_url)
            store = BlackboardStore(client, task_id=payload.blackboard_task_id, ttl=3600)
            bb = Blackboard(store, thread_id=payload.thread_id, window_tokens=2000)
            blackboard_handle = BlackboardHandle(bb)
            blackboard_handle.startup()
```

Then pass `blackboard_handle` into the subagent run so it lands on the run's
`ToolExecutionContext.blackboard` (follow exactly how Phase 2a attaches the handle in the
non-worker path — `execute_subagent` may need a `blackboard=` passthrough; add it if Phase 2a
didn't). On run completion, `blackboard_handle.shutdown()`.

- [ ] **Step 3: Smoke check (import + payload wiring)**

Run:
```bash
ENVIRONMENT=pytest .venv/bin/python -c "
import atria.core.tasks.tasks as t
from atria.core.tasks.payload import SubagentTaskPayload
p = SubagentTaskPayload(session_id='s', owner_id='o', subagent_type='solver', prompt='x', working_dir='/tmp', config_snapshot={}, blackboard_task_id='bb1', thread_id=1)
# module imports and payload carries the fields; full behavior validated in the smoke run (Task 10)
assert p.blackboard_task_id == 'bb1'
print('ok')
"
```
Expected: `ok`. (Real attach behavior is validated in Task 10.)

- [ ] **Step 4: Commit**

```bash
git add atria/core/tasks/tasks.py atria/core/agents/deps_builder.py
git commit -m "feat(parallel): attach blackboard to background solver runs"
```

---

### Task 8: Orchestrator

**Files:**
- Create: `atria/core/parallel/orchestrator.py`

**Interfaces:**
- Consumes: `snapshot_worktree`/`discard_snapshot` (T2), `JobStore` (T3), `extract_candidate` (T4), `judge_candidates` (T5), `apply_diff` (T6), `WorktreeManager`, `TaskIQClient`, the Phase 2a blackboard store/notes, and an injected `llm_call`.
- Produces: `ParallelOrchestrator(task_client, worktree_manager, job_store, redis_client, llm_call, config)` with sync `start(task, n, repo_dir, owner_id, session_id) -> str` and `collect(job_id, block=True, timeout_ms=30000) -> dict`.

- [ ] **Step 1: Implement**

```python
# atria/core/parallel/orchestrator.py
"""Two-phase parallel-solve orchestration: start (fan-out) and collect (judge + apply)."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from atria.core.parallel.apply import apply_diff
from atria.core.parallel.candidate import extract_candidate
from atria.core.parallel.job_store import JobStore
from atria.core.parallel.judge import judge_candidates
from atria.core.parallel.snapshot import snapshot_worktree

logger = logging.getLogger(__name__)


class ParallelOrchestrator:
    """Fan out N worktree-isolated solvers, judge their candidates, apply the winner."""

    def __init__(
        self,
        task_client: Any,        # Sub-project 1 TaskIQClient (sync enqueue/await)
        worktree_manager: Any,   # atria.core.git.worktree.WorktreeManager
        job_store: JobStore,
        redis_client: Any,       # async redis for reading the blackboard notes at collect
        llm_call: Callable[[str, str], str],
        config: Any,             # ParallelConfig
        run_async: Callable[[Any], Any],  # helper to run a coroutine from this sync context
    ) -> None:
        self._tc = task_client
        self._wm = worktree_manager
        self._js = job_store
        self._redis = redis_client
        self._llm = llm_call
        self._cfg = config
        self._run_async = run_async

    def start(self, task: str, n: int, repo_dir: str, owner_id: str, session_id: str) -> str:
        n = max(2, min(int(n or self._cfg.default_solvers), self._cfg.max_solvers))
        job_id = uuid.uuid4().hex[:12]
        base_ref = snapshot_worktree(repo_dir)
        blackboard_task_id = "bb_" + job_id
        worktree_names: list[str] = []
        worktree_paths: list[str] = []
        task_ids: list[str] = []
        try:
            from atria.core.tasks.payload import SubagentTaskPayload

            for i in range(n):
                wt = self._wm.create(base_branch=base_ref)
                if wt is None:
                    raise RuntimeError("worktree creation failed")
                worktree_names.append(wt.branch.replace("worktree-", ""))
                worktree_paths.append(wt.path)
                payload = SubagentTaskPayload(
                    session_id=session_id, owner_id=owner_id, subagent_type="solver",
                    prompt=task, working_dir=wt.path, config_snapshot={},
                    blackboard_task_id=blackboard_task_id, thread_id=i,
                )
                task_ids.append(self._tc.enqueue(payload))
            self._run_async(self._js.save(job_id, {
                "task_ids": task_ids, "worktree_names": worktree_names,
                "worktree_paths": worktree_paths, "blackboard_task_id": blackboard_task_id,
                "base_ref": base_ref, "repo_dir": repo_dir, "n": n, "task": task,
            }, ttl=self._cfg.pjob_ttl))
            return job_id
        except Exception:
            for name in worktree_names:
                try:
                    self._wm.remove(name, force=True)
                except Exception:  # noqa: BLE001
                    pass
            raise

    def collect(self, job_id: str, block: bool = True, timeout_ms: int = 30000) -> dict:
        rec = self._run_async(self._js.load(job_id))
        if rec is None:
            return {"status": "unknown", "error": f"no such job {job_id}"}
        results = [self._tc.await_result(tid, block=block, timeout_ms=timeout_ms)
                   for tid in rec["task_ids"]]
        done = [r for r in results if r.get("status") == "done"]
        if len(done) < len(results):
            return {"status": "running", "done": len(done), "n": rec["n"]}
        try:
            notes = self._read_notes(rec["blackboard_task_id"])
            candidates = [
                extract_candidate(rec["worktree_paths"][i], rec["base_ref"], notes, i)
                for i, r in enumerate(results) if r.get("success")
            ]
            dropped = [i for i, r in enumerate(results) if not r.get("success")]
            verdict = judge_candidates(rec["task"], candidates, self._llm)
            applied = False
            conflicted: list[str] = []
            winner_thread = -1
            if verdict.winner_index >= 0:
                winner = candidates[verdict.winner_index]
                winner_thread = winner.thread_id
                ar = apply_diff(rec["repo_dir"], winner.diff)
                applied = ar.ok
                conflicted = ar.conflicted_files
            return {
                "status": "done", "applied": applied, "winner_thread": winner_thread,
                "conflicted_files": conflicted, "reasoning": verdict.reasoning,
                "dropped_threads": dropped,
                "candidates": [{"thread": c.thread_id, "ok": c.ok, "summary": c.patch_summary}
                               for c in candidates],
                # NOTE: base_ref retained for recovery; not discarded here.
                "snapshot_ref": rec["base_ref"],
            }
        finally:
            for name in rec["worktree_names"]:
                try:
                    self._wm.remove(name, force=True)
                except Exception:  # noqa: BLE001
                    pass
            self._run_async(self._js.delete(job_id))

    def _read_notes(self, blackboard_task_id: str) -> list:
        from atria.core.blackboard.store import BlackboardStore

        store = BlackboardStore(self._redis, task_id=blackboard_task_id, ttl=self._cfg.pjob_ttl)
        return self._run_async(store.read_all())
```

- [ ] **Step 2: Smoke check (fakes)**

Run:
```bash
.venv/bin/python -c "
import asyncio
from fakeredis import aioredis as fr
from atria.core.parallel.job_store import JobStore
from atria.core.parallel.orchestrator import ParallelOrchestrator

class WT:  # fake worktree manager
    def __init__(self): self.n=0
    def create(self, base_branch=None):
        self.n+=1
        class I: path='/tmp/wt%d'%self.n; branch='worktree-wt%d'%self.n
        return I()
    def remove(self, name, force=False): return True
class TC:  # fake task client
    def __init__(self): self.k=0
    def enqueue(self, p): self.k+=1; return 'task%d'%self.k
    def await_result(self, tid, block=True, timeout_ms=0): return {'status':'done','success':True}

def run_async(coro): return asyncio.get_event_loop().run_until_complete(coro)
class Cfg: default_solvers=2; max_solvers=5; pjob_ttl=60
r = fr.FakeRedis()
orch = ParallelOrchestrator(TC(), WT(), JobStore(r), r, lambda s,u: '{\"winner_index\": -1, \"reasoning\":\"n/a\"}', Cfg(), run_async)
jid = orch.start('do it', 2, '/tmp', 'o', 's')
out = orch.collect(jid)
assert out['status']=='done', out
print('ok')
"
```
Expected: `ok` (winner -1 path; full apply path validated in Task 10).

- [ ] **Step 3: Commit**

```bash
git add atria/core/parallel/orchestrator.py
git commit -m "feat(parallel): two-phase orchestrator (start + collect)"
```

---

### Task 9: Tools (solve_parallel / get_parallel_result) + wiring

**Files:**
- Create: `atria/core/parallel/tools.py` (handlers + an orchestrator builder)
- Modify: `atria/core/agents/components/schemas/definitions.py` (two tool schemas)
- Modify: `atria/core/context_engineering/tools/registry.py` (dispatch)
- Modify: `atria/web/server.py` / per-run wiring (attach a `ParallelOrchestrator` to the run, like the task client)

**Interfaces:**
- Consumes: `ParallelOrchestrator` (T8).
- Produces: `solve_parallel(task, n)` → `{job_id, status, n}`; `get_parallel_result(job_id, block?, timeout?)` → orchestrator `collect` result. A builder that constructs the orchestrator from the run's task client + a concrete `llm_call` (from `client.chat.completions.create`, mirroring `registry.py:86`) + a sync `run_async` helper.

- [ ] **Step 1: Inspect the wiring pattern**

Run: `grep -n "task_client\|set_task_client\|attach_task_client" atria/web/server.py atria/web/agent_executor.py | head` and the `solve_parallel`-analogous tool dispatch in `registry.py`.
Mirror exactly how Sub-project 1 attaches the `TaskIQClient` (server lifespan + per-run) and how `_execute_spawn_subagent` / `_get_subagent_output` dispatch. The orchestrator needs the same `TaskIQClient` instance the run already has; build it lazily in the tool handler from the run context.

- [ ] **Step 2: Implement the tool handlers + schemas + dispatch**

`tools.py`: `execute_solve_parallel(arguments, orchestrator, repo_dir, owner_id, session_id)` and `execute_get_parallel_result(arguments, orchestrator)`; plus `build_orchestrator(task_client, repo_dir, config, llm_call, redis_client)` returning a `ParallelOrchestrator` (with a `run_async` helper using a short-lived loop or the task client's loop). Add the two schemas to `definitions.py` (string `task`, int `n`; string `job_id`, bool `block`, int `timeout`). Add dispatch in `registry.py` for `tool_name in {"solve_parallel", "get_parallel_result"}`, reading the orchestrator from the run context (built once per run, like the task client). Build `llm_call` from the project's chat-completions client (mirror `registry.py:86`).

- [ ] **Step 3: Smoke check (import)**

Run:
```bash
ENVIRONMENT=pytest .venv/bin/python -c "
from atria.core.parallel.tools import execute_solve_parallel, execute_get_parallel_result
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add atria/core/parallel/tools.py atria/core/agents/components/schemas/definitions.py atria/core/context_engineering/tools/registry.py atria/web/server.py atria/web/agent_executor.py
git commit -m "feat(parallel): solve_parallel + get_parallel_result tools + wiring"
```

---

### Task 10: Manual smoke verification (real)

**Files:** none.

Per the user's no-formal-tests decision, this is the verification step. Requires Phase 2a merged, Redis, a worker, and `OPENAI_API_KEY`.

- [ ] **Step 1: Lint the new package**

Run: `uvx ruff check atria/core/parallel atria/core/tasks/payload.py atria/models/config.py`
Expected: All checks passed (fix any issues in the new files).

- [ ] **Step 2: Import-graph smoke**

Run:
```bash
ENVIRONMENT=pytest .venv/bin/python -c "
import atria.core.parallel.snapshot, atria.core.parallel.job_store, atria.core.parallel.candidate
import atria.core.parallel.judge, atria.core.parallel.apply, atria.core.parallel.orchestrator
import atria.core.parallel.tools
print('all parallel modules import ok')
"
```
Expected: `all parallel modules import ok`.

- [ ] **Step 3: Real run**

```bash
export OPENAI_API_KEY="…"
redis-server
taskiq worker atria.core.tasks.broker:broker atria.core.tasks.tasks
make run
```
In a real git repo, have the agent call `solve_parallel("<a real, small task>", n=2)`, then `get_parallel_result(job_id)`. Verify:
- two worktrees are created off a snapshot of the current state;
- both solvers run, share notes via the blackboard, each emit a verified PATCH_SUMMARY;
- the judge picks one; its diff applies to the workspace (or conflicts surface);
- worktrees are removed; the snapshot ref is NOT destroyed (recoverable);
- by hand, also confirm the no-acceptable-candidate path (e.g. n=2 on an impossible task → `applied:false`).

- [ ] **Step 4: Commit (if any fixups)**

```bash
git add -A
git commit -m "chore(parallel): phase 2b smoke fixups"
```

---

## Self-Review

**Spec coverage**
- Snapshot incl. uncommitted → Task 2. ✓
- Payload extension (`blackboard_task_id`/`thread_id`) + worker attach → Tasks 1, 7. ✓
- Job store (Redis) → Task 3. ✓
- Candidate extraction (diff + PATCH_SUMMARY) → Task 4. ✓
- LLM judge (winner / -1) → Task 5. ✓
- Apply winner with `git apply --3way` → Task 6. ✓
- Orchestrator start/collect, clamp n, cleanup-in-finally, snapshot retained → Task 8. ✓
- Tools `solve_parallel`/`get_parallel_result` + wiring → Task 9. ✓
- Config (`ParallelConfig`) → Task 1. ✓
- Safety rails (`--3way`, retain snapshot) → Tasks 6, 8 (+ Global Constraints). ✓
- No-acceptable-candidate / partial failure / apply conflict → Tasks 5, 6, 8. ✓
- Verification: manual smoke only (per user) → Task 10. ✓

**Placeholder scan:** No "TBD/TODO" in steps. The reuse seams (LLM transport in T5/T9, blackboard attach point in T7, wiring in T9) carry concrete grep commands + the example to mirror, with full code for the deterministic logic. `discard_snapshot` is an intentional documented no-op (retain-until-confirmed rail), not a placeholder.

**Type consistency:** `Candidate{thread_id,diff,patch_summary,ok}` consistent (T4,T5,T8). `JudgeResult{winner_index,reasoning}` consistent (T5,T8). `ApplyResult{ok,conflicted_files}` consistent (T6,T8). `JobStore.save(job_id,record,ttl)/load/delete` consistent (T3,T8). `ParallelOrchestrator.start(task,n,repo_dir,owner_id,session_id)`/`collect(job_id,block,timeout_ms)` consistent (T8,T9). `SubagentTaskPayload.blackboard_task_id/thread_id` consistent (T1,T7,T8). `snapshot_worktree(repo_dir)->str` consistent (T2,T8).
