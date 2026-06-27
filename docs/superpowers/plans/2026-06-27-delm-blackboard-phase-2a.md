# DeLM Shared Verified Blackboard (Phase 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-task shared verified blackboard — typed notes written through a deterministic verifier into Redis, rendered as a deduped/prioritized digest into agent context, archived to Postgres — with a `NOTE` tool, so a single agent can write notes and see its own digest (the infra Phase 2b's parallel solvers will share).

**Architecture:** A self-contained `atria/core/blackboard/` package: pure `verifier`/`render`, a Redis-backed `store` (injectable async client, mirroring `atria/core/tasks/meta.py`), a Postgres `archive`, and a `Blackboard` async facade plus a synchronous `BlackboardHandle` proxy (background-loop bridge, same shape as `TaskIQClient`). A `NOTE` tool and a condition-gated "Shared Lessons" prompt section are the agent-facing surface.

**Tech Stack:** Python 3.11+, `redis.asyncio`, `fakeredis` (dev), Pydantic v2, SQLAlchemy async, pytest + pytest-asyncio.

## Global Constraints

- Line length 100 (Black + Ruff). Type hints on public APIs (mypy strict). Google-style docstrings.
- No new runtime deps (Redis, SQLAlchemy async, redis.asyncio already present; `fakeredis` already a dev dep).
- Note types are EXACTLY `("FACT","TRIED","OBSERVED","FAIL","CLAIM","PATCH_SUMMARY")`. Caps: `MAX_CONTENT_CHARS=100`, `MAX_PATCH_SUMMARY_CHARS=300`. PATCH_SUMMARY content schema: `files=… | idea=… | evidence=… | risk=…`.
- The blackboard is an ACCELERANT, never a hard dependency: any Redis/Postgres failure degrades gracefully (soft status / empty digest / swallowed archive), never raises into the agent run.
- Redis client is INJECTABLE and CALLER-OWNED (never opened/closed inside store/archive functions) — mirror `atria/core/tasks/meta.py` exactly. Tests use `fakeredis.aioredis.FakeRedis()`.
- Redis key prefix `atria:bb:`. Default TTL 3600s, default digest window 2000 tokens (`~4 chars/token`, ~25 chars per-entry overhead).
- Run tests with `.venv/bin/pytest` (NOT `uv run pytest`); set `ENVIRONMENT=pytest`. Per project preference, implementers run ONLY their own new test file per task; full suite is batched to the final task.
- `docs/` is gitignored → use `git add -f` for any docs file.
- Conventional Commit messages; NO `Co-Authored-By: Claude` trailer (hard project rule).

---

### Task 1: Note model + BlackboardConfig

**Files:**
- Create: `atria/core/blackboard/__init__.py`
- Create: `atria/core/blackboard/models.py`
- Modify: `atria/models/config.py` (add `BlackboardConfig`, attach to `AppConfig`)
- Test: `tests/core/blackboard/test_models.py`

**Interfaces:**
- Produces: `VALID_TYPES: tuple[str, ...]`, `MAX_CONTENT_CHARS=100`, `MAX_PATCH_SUMMARY_CHARS=300`, `Note` dataclass (`type: str`, `content: str`, `thread_id: int`, `ts: float`) with `to_dict()`/`from_dict()`; `BlackboardConfig(redis_url, ttl, window_tokens)`; `AppConfig.blackboard: BlackboardConfig`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_models.py
from atria.core.blackboard.models import (
    MAX_CONTENT_CHARS,
    MAX_PATCH_SUMMARY_CHARS,
    VALID_TYPES,
    Note,
)


def test_valid_types_and_caps():
    assert VALID_TYPES == ("FACT", "TRIED", "OBSERVED", "FAIL", "CLAIM", "PATCH_SUMMARY")
    assert MAX_CONTENT_CHARS == 100
    assert MAX_PATCH_SUMMARY_CHARS == 300


def test_note_roundtrips_dict():
    n = Note(type="FACT", content="x.py:1 does y", thread_id=0, ts=123.0)
    d = n.to_dict()
    assert d == {"type": "FACT", "content": "x.py:1 does y", "thread_id": 0, "ts": 123.0}
    assert Note.from_dict(d) == n
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_models.py -v`
Expected: FAIL — module not found. (Create `tests/core/blackboard/__init__.py` if collection needs it.)

- [ ] **Step 3: Implement models + config**

```python
# atria/core/blackboard/__init__.py
"""Shared verified blackboard (DeLM port, Sub-project 2 Phase 2a)."""
```

```python
# atria/core/blackboard/models.py
"""Typed-note model and size caps for the shared blackboard."""
from __future__ import annotations

from dataclasses import dataclass

VALID_TYPES: tuple[str, ...] = ("FACT", "TRIED", "OBSERVED", "FAIL", "CLAIM", "PATCH_SUMMARY")
MAX_CONTENT_CHARS = 100
# PATCH_SUMMARY uses the structured "files=A | idea=B | evidence=C | risk=D" schema,
# which doesn't fit the 100-char durable-note cap.
MAX_PATCH_SUMMARY_CHARS = 300


@dataclass(frozen=True)
class Note:
    """One typed entry on the blackboard."""

    type: str
    content: str
    thread_id: int
    ts: float

    def to_dict(self) -> dict:
        return {"type": self.type, "content": self.content,
                "thread_id": self.thread_id, "ts": self.ts}

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        return cls(type=d["type"], content=d["content"],
                   thread_id=int(d["thread_id"]), ts=float(d["ts"]))
```

In `atria/models/config.py`, below `TasksConfig` (added in Sub-project 1), add:

```python
class BlackboardConfig(BaseModel):
    """Shared verified blackboard (DeLM) settings."""

    redis_url: str = "redis://localhost:6379/0"
    ttl: int = 3600  # seconds a task's blackboard lives in Redis
    window_tokens: int = 2000  # digest token budget injected into context
```

And in `AppConfig`, alongside `tasks`:

```python
    blackboard: BlackboardConfig = Field(default_factory=BlackboardConfig)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/__init__.py atria/core/blackboard/models.py atria/models/config.py tests/core/blackboard/
git commit -m "feat(blackboard): note model + BlackboardConfig"
```

---

### Task 2: Deterministic verifier (port of DeLM verify_notes)

**Files:**
- Create: `atria/core/blackboard/verifier.py`
- Test: `tests/core/blackboard/test_verifier.py`

**Interfaces:**
- Consumes: `VALID_TYPES`, `MAX_CONTENT_CHARS`, `MAX_PATCH_SUMMARY_CHARS` (Task 1).
- Produces: `verify_notes(notes: list[dict]) -> tuple[list[dict], str]` (clean notes + `ok:{kept}/{seen}` status; never raises, no LLM).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_verifier.py
from atria.core.blackboard.verifier import verify_notes


def test_normalizes_type_and_drops_invalid():
    clean, status = verify_notes([{"type": "fact", "content": "a"}, {"type": "BOGUS", "content": "b"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"


def test_drops_empty_and_caps_length():
    long = "x" * 250
    clean, _ = verify_notes([{"type": "FACT", "content": long}, {"type": "FACT", "content": "  "}])
    assert len(clean) == 1
    assert len(clean[0]["content"]) == 100  # MAX_CONTENT_CHARS


def test_patch_summary_keeps_300_and_rejects_placeholder_evidence():
    good = "files=a.py | idea=fix | evidence=ran test_x and it PASSED | risk=none"
    bad = "files=a.py | idea=fix | evidence=TBD | risk=none"
    clean, status = verify_notes([{"type": "PATCH_SUMMARY", "content": good},
                                  {"type": "PATCH_SUMMARY", "content": bad}])
    assert clean == [{"type": "PATCH_SUMMARY", "content": good}]
    assert "ps_invalid_ev=1" in status


def test_collapses_exact_duplicates():
    clean, status = verify_notes([{"type": "FACT", "content": "a"}, {"type": "FACT", "content": "a"}])
    assert clean == [{"type": "FACT", "content": "a"}]
    assert status == "ok:1/2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_verifier.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the verifier (port from `.references/DeLM/src/verifier.py`)**

```python
# atria/core/blackboard/verifier.py
"""Deterministic note hygiene — ported from DeLM src/verifier.py. No LLM, never raises."""
from __future__ import annotations

from atria.core.blackboard.models import (
    MAX_CONTENT_CHARS,
    MAX_PATCH_SUMMARY_CHARS,
    VALID_TYPES,
)

_INVALID_EVIDENCE_PHRASES = (
    "tbd", "pending", "not verified", "unverified", "should work", "should pass",
    "looks right", "looks correct", "seems to work", "to be verified", "will verify", "n/a",
)


def _parse_schema_field(content: str, field_name: str) -> str | None:
    if not content:
        return None
    prefix = field_name.lower() + "="
    for part in content.split("|"):
        s = part.strip()
        if s.lower().startswith(prefix):
            return s[len(prefix):].strip()
    return None


def _is_invalid_patch_summary_evidence(content: str) -> bool:
    ev = _parse_schema_field(content, "evidence")
    if ev is None:
        return True
    norm = ev.strip().lower()
    if not norm:
        return True
    for p in _INVALID_EVIDENCE_PHRASES:
        if norm == p:
            return True
        if norm.startswith(p):
            tail = norm[len(p):]
            if not tail or not tail[0].isalpha():
                return True
    return False


def verify_notes(notes: list[dict]) -> tuple[list[dict], str]:
    """Type-normalize, cap per type, reject placeholder PATCH_SUMMARY evidence, dedupe.

    Returns (clean_notes, status). status is "ok:{kept}/{seen}", plus
    ",ps_invalid_ev={n}" when n PATCH_SUMMARYs were dropped for bad evidence.
    """
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []
    n_in = len(notes or [])
    ps_dropped = 0
    for note in notes or []:
        t = str(note.get("type", "")).strip().upper()
        c = str(note.get("content", "")).strip()
        if t not in VALID_TYPES or not c:
            continue
        cap = MAX_PATCH_SUMMARY_CHARS if t == "PATCH_SUMMARY" else MAX_CONTENT_CHARS
        if len(c) > cap:
            c = c[:cap]
        if t == "PATCH_SUMMARY" and _is_invalid_patch_summary_evidence(c):
            ps_dropped += 1
            continue
        key = (t, c)
        if key in seen:
            continue
        seen.add(key)
        clean.append({"type": t, "content": c})
    status = f"ok:{len(clean)}/{n_in}"
    if ps_dropped:
        status += f",ps_invalid_ev={ps_dropped}"
    return clean, status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_verifier.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/verifier.py tests/core/blackboard/test_verifier.py
git commit -m "feat(blackboard): deterministic note verifier (DeLM port)"
```

---

### Task 3: Digest renderer (pure)

**Files:**
- Create: `atria/core/blackboard/render.py`
- Test: `tests/core/blackboard/test_render.py`

**Interfaces:**
- Consumes: `Note`, `VALID_TYPES` (Task 1).
- Produces: `render_digest(notes: list[Note], viewer_id: int, window_tokens: int) -> str` — deduped, priority-ordered, budget-truncated digest; each line `[t{thread_id}/{TYPE}] {content}`; empty input → `""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_render.py
from atria.core.blackboard.models import Note
from atria.core.blackboard.render import render_digest


def _n(t, c, thread=0, ts=0.0):
    return Note(type=t, content=c, thread_id=thread, ts=ts)


def test_empty_returns_empty_string():
    assert render_digest([], viewer_id=0, window_tokens=2000) == ""


def test_dedup_and_format():
    out = render_digest([_n("FACT", "a"), _n("FACT", "a")], viewer_id=0, window_tokens=2000)
    assert out.count("[t0/FACT] a") == 1


def test_priority_orders_patch_summary_first():
    notes = [_n("TRIED", "did x", ts=2.0), _n("PATCH_SUMMARY", "files=a | idea=b | evidence=ran t PASSED | risk=n", ts=1.0)]
    out = render_digest(notes, viewer_id=0, window_tokens=2000)
    assert out.index("PATCH_SUMMARY") < out.index("TRIED")


def test_token_budget_truncates():
    notes = [_n("FACT", "x" * 80, thread=i, ts=float(i)) for i in range(50)]
    out = render_digest(notes, viewer_id=0, window_tokens=50)  # ~200 chars budget
    assert len(out) <= 50 * 4
    assert out  # non-empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_render.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the renderer**

```python
# atria/core/blackboard/render.py
"""Pure digest rendering: dedup + simple priority + token-budget truncation."""
from __future__ import annotations

from atria.core.blackboard.models import Note

_PRIORITY = {"PATCH_SUMMARY": 0, "CLAIM": 1, "FAIL": 2, "FACT": 3, "OBSERVED": 4, "TRIED": 5}
_CHARS_PER_TOKEN = 4
_FORMAT_OVERHEAD_CHARS = 25


def render_digest(notes: list[Note], viewer_id: int, window_tokens: int) -> str:
    """Render a deduped, priority-ordered, budget-truncated digest.

    Args:
        notes: All notes currently on the blackboard.
        viewer_id: The reading thread's id (reserved for 2b peer framing; unused in 2a
            beyond inclusion).
        window_tokens: Token budget; entries beyond it are dropped (priority, then newest).

    Returns:
        Newline-joined "[t{thread}/{TYPE}] {content}" lines, or "" when nothing fits.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Note] = []
    for n in notes:
        key = (n.type, n.content)
        if key in seen:
            continue
        seen.add(key)
        unique.append(n)
    # priority asc, then newest (ts desc)
    unique.sort(key=lambda n: (_PRIORITY.get(n.type, 9), -n.ts))

    budget = window_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    used = 0
    for n in unique:
        line = f"[t{n.thread_id}/{n.type}] {n.content}"
        cost = len(line) + _FORMAT_OVERHEAD_CHARS
        if used + cost > budget:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_render.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/render.py tests/core/blackboard/test_render.py
git commit -m "feat(blackboard): deduped priority digest renderer"
```

---

### Task 4: Redis store (injectable client)

**Files:**
- Create: `atria/core/blackboard/store.py`
- Test: `tests/core/blackboard/test_store.py`

**Interfaces:**
- Consumes: `Note` (Task 1).
- Produces: `BlackboardStore(redis, task_id, ttl)` with async `append(notes: list[Note]) -> None` and `read_all() -> list[Note]`. Key `atria:bb:{task_id}`. Caller owns the redis client (never closed here).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_store.py
import pytest

from atria.core.blackboard.models import Note
from atria.core.blackboard.store import BlackboardStore


@pytest.mark.asyncio
async def test_append_then_read_roundtrip():
    from fakeredis import aioredis as fake_aioredis

    r = fake_aioredis.FakeRedis()
    store = BlackboardStore(r, task_id="t1", ttl=60)
    await store.append([Note("FACT", "a", 0, 1.0), Note("TRIED", "b", 0, 2.0)])
    await store.append([Note("OBSERVED", "c", 1, 3.0)])
    notes = await store.read_all()
    assert [n.content for n in notes] == ["a", "b", "c"]
    assert notes[2].thread_id == 1


@pytest.mark.asyncio
async def test_read_all_empty_is_empty_list():
    from fakeredis import aioredis as fake_aioredis

    store = BlackboardStore(fake_aioredis.FakeRedis(), task_id="none", ttl=60)
    assert await store.read_all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_store.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the store (mirror `atria/core/tasks/meta.py` lifecycle conventions)**

```python
# atria/core/blackboard/store.py
"""Redis hot-path store for a task's blackboard notes.

The caller owns the redis client lifecycle (create, pass in, close). This class
never opens or closes connections — mirrors atria/core/tasks/meta.py.
"""
from __future__ import annotations

import json

from atria.core.blackboard.models import Note

_PREFIX = "atria:bb:"


class BlackboardStore:
    """Append-only note list for one task, keyed atria:bb:{task_id}."""

    def __init__(self, redis: object, task_id: str, ttl: int) -> None:
        self._redis = redis
        self._key = _PREFIX + task_id
        self._ttl = ttl

    async def append(self, notes: list[Note]) -> None:
        """RPUSH each note as JSON and refresh the TTL. No-op for an empty list."""
        if not notes:
            return
        payloads = [json.dumps(n.to_dict()) for n in notes]
        await self._redis.rpush(self._key, *payloads)  # type: ignore[attr-defined]
        await self._redis.expire(self._key, self._ttl)  # type: ignore[attr-defined]

    async def read_all(self) -> list[Note]:
        """Return all notes in insertion order."""
        raw = await self._redis.lrange(self._key, 0, -1)  # type: ignore[attr-defined]
        out: list[Note] = []
        for item in raw or []:
            s = item.decode() if isinstance(item, bytes) else item
            out.append(Note.from_dict(json.loads(s)))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_store.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/store.py tests/core/blackboard/test_store.py
git commit -m "feat(blackboard): redis store with injectable client"
```

---

### Task 5: Postgres archive

**Files:**
- Create: `atria/core/blackboard/archive.py`
- Modify: the ORM models module (find with `grep -rn "class Conversation" atria/` — add `BlackboardNote` next to it, same `Base`)
- Test: `tests/core/blackboard/test_archive.py`

**Interfaces:**
- Consumes: `Note` (Task 1).
- Produces: `async archive_to_postgres(session_factory, task_id: str, owner_id: str, notes: list[Note]) -> int` — inserts one `BlackboardNote` row per note; returns the count written; best-effort (logs + returns 0 on failure, never raises).

- [ ] **Step 1: Inspect the ORM setup**

Run: `grep -rn "class Conversation\|class Message\|Base = \|DeclarativeBase\|metadata" atria/core/context_engineering/history/ | head`
Identify the SQLAlchemy `Base`/declarative setup and the async `session_factory`/`sessionmaker` used by `pg_manager.py`. The `BlackboardNote` model must use the SAME `Base`, and the archive must accept the SAME async session factory `pg_manager` uses.

- [ ] **Step 2: Write the failing test**

```python
# tests/core/blackboard/test_archive.py
import pytest

from atria.core.blackboard.archive import archive_to_postgres
from atria.core.blackboard.models import Note


@pytest.mark.asyncio
async def test_archive_writes_rows(monkeypatch):
    captured = []

    class _Session:
        def add(self, obj):
            captured.append(obj)
        async def commit(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass

    def _factory():
        return _Session()

    n = await archive_to_postgres(_factory, "t1", "u1", [Note("FACT", "a", 0, 1.0)])
    assert n == 1
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_archive_swallows_failure(monkeypatch):
    def _factory():
        raise RuntimeError("db down")

    n = await archive_to_postgres(_factory, "t1", "u1", [Note("FACT", "a", 0, 1.0)])
    assert n == 0  # best-effort, no raise
```

- [ ] **Step 3: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_archive.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Add the ORM model + implement archive**

In the ORM models module (same one defining `Conversation`), add:

```python
class BlackboardNote(Base):
    """Archived blackboard note (post-hoc inspection only)."""

    __tablename__ = "blackboard_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, index=True, nullable=False)
    owner_id = Column(String, nullable=True)
    thread_id = Column(Integer, nullable=False)
    type = Column(String, nullable=False)
    content = Column(String, nullable=False)
    ts = Column(Float, nullable=False)
```

(Match the import style already used in that file — `Column`, `Integer`, `String`, `Float` from sqlalchemy. If the project uses `Mapped`/`mapped_column`, follow THAT style instead — mirror the existing `Conversation`/`Message` definitions exactly.)

```python
# atria/core/blackboard/archive.py
"""Best-effort Postgres archive of a task's final blackboard (inspection only)."""
from __future__ import annotations

import logging
from typing import Callable

from atria.core.blackboard.models import Note

logger = logging.getLogger(__name__)


async def archive_to_postgres(
    session_factory: Callable[[], object],
    task_id: str,
    owner_id: str,
    notes: list[Note],
) -> int:
    """Insert one row per note. Returns rows written; 0 on any failure (never raises).

    Args:
        session_factory: Callable returning an async session context manager
            (the same one pg_manager uses).
        task_id: The task whose blackboard this is.
        owner_id: Owner/user id for the run.
        notes: Final blackboard notes to archive.
    """
    if not notes:
        return 0
    try:
        from atria.core.context_engineering.history.session_manager.models import (  # adjust import
            BlackboardNote,
        )

        session = session_factory()
        async with session as s:
            for n in notes:
                s.add(BlackboardNote(
                    task_id=task_id, owner_id=owner_id, thread_id=n.thread_id,
                    type=n.type, content=n.content, ts=n.ts,
                ))
            await s.commit()
        return len(notes)
    except Exception as exc:  # noqa: BLE001 — archive is best-effort
        logger.warning("blackboard archive failed for %s: %s", task_id, exc)
        return 0
```

(Fix the `BlackboardNote` import path to wherever you added the model in Step 4.)

- [ ] **Step 5: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_archive.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add atria/core/blackboard/archive.py tests/core/blackboard/test_archive.py <orm-models-file>
git commit -m "feat(blackboard): postgres archive + BlackboardNote model"
```

---

### Task 6: Blackboard facade + sync handle

**Files:**
- Create: `atria/core/blackboard/blackboard.py`
- Test: `tests/core/blackboard/test_blackboard.py`

**Interfaces:**
- Consumes: `verify_notes` (T2), `render_digest` (T3), `BlackboardStore` (T4), `archive_to_postgres` (T5), `Note` (T1).
- Produces:
  - `Blackboard(store, *, thread_id=0, window_tokens=2000, session_factory=None, owner_id="")` async facade: `async write(raw_notes: list[dict]) -> str`, `async render(viewer_id: int | None = None) -> str`, `async archive() -> int`.
  - `BlackboardHandle(blackboard)` sync proxy (background-loop bridge, same shape as `TaskIQClient`): `startup()`, `shutdown()`, `write(raw_notes) -> str`, `render() -> str`, `archive() -> int`. On any underlying error, `write` returns `"blackboard unavailable"` and `render` returns `""` (graceful degradation).

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_blackboard.py
import pytest

from atria.core.blackboard.blackboard import Blackboard
from atria.core.blackboard.store import BlackboardStore


def _bb(thread_id=0):
    from fakeredis import aioredis as fake_aioredis

    store = BlackboardStore(fake_aioredis.FakeRedis(), task_id="t1", ttl=60)
    return Blackboard(store, thread_id=thread_id, window_tokens=2000)


@pytest.mark.asyncio
async def test_write_verifies_then_render_shows_kept_notes():
    bb = _bb(thread_id=2)
    status = await bb.write([{"type": "fact", "content": "found it"},
                             {"type": "BOGUS", "content": "drop me"}])
    assert status == "ok:1/2"
    digest = await bb.render()
    assert "[t2/FACT] found it" in digest
    assert "drop me" not in digest


@pytest.mark.asyncio
async def test_write_none_keeps_nothing():
    bb = _bb()
    status = await bb.write([])
    assert status == "ok:0/0"
    assert await bb.render() == ""


@pytest.mark.asyncio
async def test_write_degrades_when_store_raises():
    class _BoomStore:
        async def append(self, notes):
            raise RuntimeError("redis down")
        async def read_all(self):
            raise RuntimeError("redis down")

    bb = Blackboard(_BoomStore(), thread_id=0, window_tokens=2000)
    assert await bb.write([{"type": "FACT", "content": "x"}]) == "blackboard unavailable"
    assert await bb.render() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_blackboard.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the facade + sync handle**

```python
# atria/core/blackboard/blackboard.py
"""Blackboard facade (async) + synchronous handle (background-loop bridge)."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from atria.core.blackboard.archive import archive_to_postgres
from atria.core.blackboard.models import Note
from atria.core.blackboard.render import render_digest
from atria.core.blackboard.verifier import verify_notes

logger = logging.getLogger(__name__)


class Blackboard:
    """Compose verifier + store + render + archive for one task."""

    def __init__(
        self,
        store: Any,
        *,
        thread_id: int = 0,
        window_tokens: int = 2000,
        session_factory: Callable[[], object] | None = None,
        owner_id: str = "",
    ) -> None:
        self._store = store
        self._thread_id = thread_id
        self._window_tokens = window_tokens
        self._session_factory = session_factory
        self._owner_id = owner_id
        self._task_id = getattr(store, "_key", "atria:bb:?").removeprefix("atria:bb:")

    async def write(self, raw_notes: list[dict]) -> str:
        """Verify then append notes. Returns the verifier status, or a soft-failure string."""
        clean, status = verify_notes(raw_notes)
        if not clean:
            return status
        try:
            now = self._now()
            await self._store.append(
                [Note(type=c["type"], content=c["content"], thread_id=self._thread_id, ts=now)
                 for c in clean]
            )
        except Exception as exc:  # noqa: BLE001 — accelerant, never hard-fail
            logger.warning("blackboard write failed: %s", exc)
            return "blackboard unavailable"
        return status

    async def render(self, viewer_id: int | None = None) -> str:
        """Render the current digest, or "" on any failure."""
        try:
            notes = await self._store.read_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("blackboard render failed: %s", exc)
            return ""
        vid = self._thread_id if viewer_id is None else viewer_id
        return render_digest(notes, viewer_id=vid, window_tokens=self._window_tokens)

    async def archive(self) -> int:
        """Flush the final blackboard to Postgres (best-effort)."""
        if self._session_factory is None:
            return 0
        try:
            notes = await self._store.read_all()
        except Exception:  # noqa: BLE001
            return 0
        return await archive_to_postgres(self._session_factory, self._task_id, self._owner_id, notes)

    @staticmethod
    def _now() -> float:
        import time

        return time.time()


class BlackboardHandle:
    """Synchronous proxy over Blackboard for the (loopless) agent thread.

    Owns one persistent daemon-thread event loop, same shape as
    atria.core.tasks.client.TaskIQClient.
    """

    def __init__(self, blackboard: Blackboard) -> None:
        self._bb = blackboard
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._started = False

    def startup(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._started = True

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def shutdown(self) -> None:
        if not self._started or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._started = False

    def _submit(self, coro: Any) -> Any:
        self.startup()
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def write(self, raw_notes: list[dict]) -> str:
        try:
            return self._submit(self._bb.write(raw_notes))
        except Exception as exc:  # noqa: BLE001
            logger.warning("blackboard handle write failed: %s", exc)
            return "blackboard unavailable"

    def render(self) -> str:
        try:
            return self._submit(self._bb.render())
        except Exception:  # noqa: BLE001
            return ""

    def archive(self) -> int:
        try:
            return self._submit(self._bb.archive())
        except Exception:  # noqa: BLE001
            return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_blackboard.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/blackboard.py tests/core/blackboard/test_blackboard.py
git commit -m "feat(blackboard): facade + synchronous handle bridge"
```

---

### Task 7: NOTE tool

**Files:**
- Create: `atria/core/blackboard/note_rules.py` (the tool-description block, ported from DeLM)
- Create: `atria/core/context_engineering/tools/implementations/note_tool.py`
- Modify: `atria/core/agents/components/schemas/definitions.py` (register the `NOTE` tool schema)
- Modify: `atria/core/context_engineering/tools/registry.py` (handler dispatch; the tool gets the run's `BlackboardHandle`)
- Test: `tests/core/context_engineering/test_note_tool.py`

**Interfaces:**
- Consumes: `BlackboardHandle.write` (T6), `verify_notes` semantics (T2).
- Produces: a `NOTE` tool that parses a body of up to 3 `<TYPE> <content>` lines (or the literal `(none)`), calls `handle.write([...])`, and returns `{"success": True, "output": "<status>"}`. Pure parse helper `parse_note_body(text: str) -> list[dict]`.

- [ ] **Step 1: Inspect the tool-wiring pattern**

Run: `sed -n '1438,1465p' atria/core/agents/components/schemas/definitions.py` (the `get_subagent_output` schema) and `grep -n "_get_subagent_output\|elif tool_name ==" atria/core/context_engineering/tools/registry.py | head`
Mirror exactly how an existing simple tool declares its schema and how `registry.py` dispatches `tool_name` to a handler method. The NOTE handler reads the run's blackboard handle from the execution context (see Task 8 for how it's attached) via `getattr(context, "blackboard", None)`.

- [ ] **Step 2: Write the failing test**

```python
# tests/core/context_engineering/test_note_tool.py
from atria.core.context_engineering.tools.implementations.note_tool import (
    execute_note,
    parse_note_body,
)


def test_parse_multiline_body():
    body = "FACT a.py:1 does x\nTRIED added guard\n(none)"
    parsed = parse_note_body(body)
    assert {"type": "FACT", "content": "a.py:1 does x"} in parsed
    assert {"type": "TRIED", "content": "added guard"} in parsed
    assert all(p["content"] != "(none)" for p in parsed)


def test_parse_none_only_is_empty():
    assert parse_note_body("(none)") == []


def test_execute_note_writes_via_handle():
    class _Handle:
        def __init__(self):
            self.calls = []
        def write(self, notes):
            self.calls.append(notes)
            return "ok:1/1"

    h = _Handle()
    out = execute_note({"body": "FACT found it"}, blackboard=h)
    assert out["success"] is True
    assert out["output"] == "ok:1/1"
    assert h.calls == [[{"type": "FACT", "content": "found it"}]]


def test_execute_note_without_blackboard_is_soft_noop():
    out = execute_note({"body": "FACT x"}, blackboard=None)
    assert out["success"] is True
    assert "no blackboard" in out["output"].lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/context_engineering/test_note_tool.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement note_rules + the tool**

```python
# atria/core/blackboard/note_rules.py
"""NOTE tool description block, ported from .references/DeLM/src/prompts/note_rules.py."""

NOTE_RULES_BLOCK = """NOTE writes short typed entries to the SHARED LESSONS blackboard so other
parallel solvers can see your findings. Each entry is one line: <TYPE> <content>
TYPE must be EXACTLY one of: FACT | TRIED | OBSERVED | FAIL | CLAIM | PATCH_SUMMARY
  - FACT: objective discovery (file path, function signature, error text)
  - TRIED: action you just took (one-line summary)
  - OBSERVED: empirical result (test output, exit code)
  - FAIL: a failed attempt with brief reason (so other solvers don't repeat it)
  - CLAIM: your CURRENT TARGET / hypothesis before expensive work. SPARSE: at most ONE
    when starting a distinct hypothesis, a SECOND only after a real pivot.
  - PATCH_SUMMARY: a concise summary of a CANDIDATE FIX you ACTUALLY applied (not a plan),
    using the 4-field schema separated by ` | `:
      files=<comma-separated paths> | idea=<one-sentence patch idea> |
      evidence=<what verified it works> | risk=<known regression risk>
    Emit ONCE after the patch is applied and checked. Up to ~300 chars.
Content size: FACT/TRIED/OBSERVED/FAIL/CLAIM <=100 chars; PATCH_SUMMARY <=300. Write 0-3
entries per turn. If nothing is worth sharing, write the literal `(none)`.
Examples:
  FACT app/parsers/options.py:88 drops blank label fallback
  OBSERVED demo_checks.py::test_blank_label FAILED with ValueError
  PATCH_SUMMARY files=app/formatters/labels.py | idea=preserve blank labels | evidence=ran test_blank_label PASSED | risk=may keep whitespace labels
  (none)"""
```

```python
# atria/core/context_engineering/tools/implementations/note_tool.py
"""The NOTE tool: write verified typed notes to the run's shared blackboard."""
from __future__ import annotations

from typing import Any

_NONE = "(none)"


def parse_note_body(text: str) -> list[dict]:
    """Parse up to a few `<TYPE> <content>` lines into note dicts. `(none)` lines are skipped."""
    notes: list[dict] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.lower() == _NONE:
            continue
        parts = s.split(None, 1)
        if len(parts) != 2:
            continue
        notes.append({"type": parts[0].strip(), "content": parts[1].strip()})
    return notes


def execute_note(arguments: dict[str, Any], blackboard: Any = None) -> dict[str, Any]:
    """Write the parsed notes to the blackboard handle; soft no-op if none attached."""
    parsed = parse_note_body(arguments.get("body", ""))
    if blackboard is None:
        return {"success": True, "output": "no blackboard attached; note skipped"}
    if not parsed:
        return {"success": True, "output": "ok:0/0"}
    status = blackboard.write(parsed)
    return {"success": True, "output": status}
```

- [ ] **Step 5: Register the schema + dispatch**

In `definitions.py`, add a `NOTE` tool schema (mirror the existing simple-tool shape) with a single required string property `body`, and `description = NOTE_RULES_BLOCK` (import it). In `registry.py`, dispatch `tool_name == "NOTE"` to a handler that calls `execute_note(arguments, blackboard=getattr(context, "blackboard", None))`. Follow the exact dispatch pattern used for `get_subagent_output`.

- [ ] **Step 6: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/context_engineering/test_note_tool.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add atria/core/blackboard/note_rules.py atria/core/context_engineering/tools/implementations/note_tool.py atria/core/agents/components/schemas/definitions.py atria/core/context_engineering/tools/registry.py tests/core/context_engineering/test_note_tool.py
git commit -m "feat(blackboard): NOTE tool + schema + registry dispatch"
```

---

### Task 8: Context injection + blackboard attach

**Files:**
- Modify: `atria/core/context_engineering/tools/context.py` (add `blackboard: Optional[Any] = None` to `ToolExecutionContext`)
- Create: a "Shared Lessons" prompt section (find the section pattern with `grep -rn "PromptComposer\|register_section\|templates/system/main" atria/core/agents/`)
- Modify: the prompt composition wiring to inject `blackboard.render()` when a blackboard is attached
- Test: `tests/core/blackboard/test_context_injection.py`

**Interfaces:**
- Consumes: `BlackboardHandle.render` (T6).
- Produces: `render_shared_lessons_section(blackboard) -> str` returning a titled section (e.g. `"## Shared Lessons\n<digest>"`) when a non-empty digest exists, else `""`; `ToolExecutionContext.blackboard` field.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/blackboard/test_context_injection.py
from atria.core.blackboard.injection import render_shared_lessons_section


def test_section_empty_when_no_blackboard():
    assert render_shared_lessons_section(None) == ""


def test_section_empty_when_digest_blank():
    class _H:
        def render(self):
            return ""
    assert render_shared_lessons_section(_H()) == ""


def test_section_wraps_digest():
    class _H:
        def render(self):
            return "[t0/FACT] a"
    out = render_shared_lessons_section(_H())
    assert "Shared Lessons" in out
    assert "[t0/FACT] a" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_context_injection.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the injection helper + wire it**

```python
# atria/core/blackboard/injection.py
"""Render the Shared Lessons context section from a blackboard handle."""
from __future__ import annotations

from typing import Any

_HEADER = "## Shared Lessons (verified notes from this task's solvers)\n"


def render_shared_lessons_section(blackboard: Any) -> str:
    """Return a titled digest section, or "" when there is nothing to show."""
    if blackboard is None:
        return ""
    digest = blackboard.render()
    if not digest:
        return ""
    return _HEADER + digest
```

Add `blackboard: Optional[Any] = None` to `ToolExecutionContext` (`context.py`). Then wire `render_shared_lessons_section` into the prompt composition so it is injected before the LLM call when the run has a blackboard attached — follow the existing `PromptComposer` section-registration pattern (condition: blackboard present). Pass the run's `BlackboardHandle` into the `ToolExecutionContext` where the other managers are set (so the NOTE tool from Task 7 reaches it).

- [ ] **Step 4: Run test to verify it passes**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/test_context_injection.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add atria/core/blackboard/injection.py atria/core/context_engineering/tools/context.py tests/core/blackboard/test_context_injection.py <prompt-composition-file>
git commit -m "feat(blackboard): Shared Lessons context injection + context attach"
```

---

### Task 9: Full suite + real e2e

**Files:** none (verification). Per CLAUDE.md: unit tests AND a real run with `OPENAI_API_KEY`.

- [ ] **Step 1: Run the full blackboard suite**

Run: `ENVIRONMENT=pytest .venv/bin/pytest tests/core/blackboard/ tests/core/context_engineering/test_note_tool.py -q`
Expected: all pass.

- [ ] **Step 2: Run the project suite + interpret**

Run: `ENVIRONMENT=pytest .venv/bin/pytest -q`
Expected: no NEW failures vs the pre-existing baseline (the project has pre-existing failures from the Postgres-session-storage migration — confirm none of the new failures reference `blackboard`).

- [ ] **Step 3: Lint the new files**

Run: `uvx ruff check atria/core/blackboard tests/core/blackboard atria/core/context_engineering/tools/implementations/note_tool.py`
Expected: All checks passed (fix any F401/E-class issues in the new files).

- [ ] **Step 4: Real e2e**

```bash
export OPENAI_API_KEY="…"
redis-server                    # or existing Redis
make run
```
Attach a blackboard to a run (behind the Phase-2a flag), prompt the agent to investigate something and emit `NOTE` entries across 2+ turns. Verify: (a) the NOTE tool returns `ok:n/m` statuses, (b) the "Shared Lessons" section appears in the next turn's context with the verified notes, (c) a PATCH_SUMMARY with placeholder evidence (`TBD`) is rejected, (d) on completion the notes archive to the `blackboard_notes` table.

- [ ] **Step 5: Commit (if any fixups)**

```bash
git add -A
git commit -m "test(blackboard): verify phase 2a end-to-end"
```

---

## Self-Review

**Spec coverage**
- 6 typed notes + caps + PATCH_SUMMARY schema → Task 1. ✓
- Deterministic verifier (type/cap/placeholder-evidence/dedup, `ok:k/n` status) → Task 2. ✓
- Deduped + simple-priority digest renderer with token budget → Task 3. ✓
- Redis store, injectable client, `atria:bb:` prefix, TTL → Task 4. ✓
- Postgres archive + `blackboard_notes` table, best-effort → Task 5. ✓
- Blackboard facade + sync bridge (TaskIQClient-shape loop) → Task 6. ✓
- NOTE tool (parse 0–3 lines / `(none)`, returns status) + note-rules block → Task 7. ✓
- Context injection (condition-gated Shared Lessons section) + `ToolExecutionContext.blackboard` → Task 8. ✓
- Config (`BlackboardConfig` on `AppConfig`) → Task 1. ✓
- Graceful degradation (Redis/Postgres failures never raise) → Tasks 5, 6, 7, 8. ✓
- Testing: unit + real e2e with OPENAI_API_KEY → Task 9. ✓

**Placeholder scan:** No "TBD/TODO" in steps. The codebase-specific seams (ORM `Base` style in Task 5; tool dispatch + PromptComposer section in Tasks 7–8) carry concrete grep commands and the example to mirror, with full code for the new logic — not deferred work.

**Type consistency:** `verify_notes(list[dict])->(list[dict],str)` consistent (T2,T6). `Note(type,content,thread_id,ts)` + `to_dict/from_dict` consistent (T1,T4,T6). `BlackboardStore(redis,task_id,ttl)` with `append(list[Note])`/`read_all()->list[Note]` consistent (T4,T6). `Blackboard.write/render/archive` and `BlackboardHandle` sync mirror consistent (T6,T7,T8). `parse_note_body`/`execute_note(arguments, blackboard=)` consistent (T7). `render_shared_lessons_section(blackboard)` consistent (T8). Note-type tuple and caps identical across T1/T2/T3.
