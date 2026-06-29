# DeLM Shared Verified Blackboard — Design (Sub-project 2, Phase 2a)

**Date:** 2026-06-27
**Status:** Approved design, pending implementation plan
**Scope:** Phase 2a of Sub-project 2 — the shared verified blackboard, standalone.
Phase 2b (the `solve_parallel` tool, N-way worktree-isolated fan-out, the judge,
and apply-winner) is a separate cycle built on this.

## Context

We are porting DeLM's architecture (`.references/DeLM/`) onto atria. Sub-project 1
(shipped) added a TaskIQ background-subagent substrate. Sub-project 2 adds DeLM's
**parallel best-of-N solvers + shared verified blackboard**.

DeLM runs N solver threads on one task. Each thread owns an isolated workspace
(Docker container in DeLM; a git worktree in atria) and writes compact **typed
notes** to a shared `SharedLessons` blackboard; peers read a verified, deduped
digest before planning/implementing. The paper's real value is that the shared
**verified context makes each solver better** (the `avg@1` metric) by avoiding
duplicated work — `pass@N` is an upper bound. The final answer is one workspace's
result, selected by evidence.

### Decisions locked during brainstorming (whole of Sub-project 2)

- **Selection model:** an LLM **judge** picks the best of N candidate solutions.
  Each solver works in its own git worktree and posts a verified candidate-solution
  note; at the join, a judge compares the N candidates (diffs + evidence) and the
  winner's worktree diff is applied to the user's workspace. (Phase 2b.)
- **Trigger/unit:** a new `solve_parallel(task, n)` tool the main agent calls when a
  task warrants N solvers. (Phase 2b.)
- **Blackboard storage:** Redis hot path + Postgres archive.
- **Phasing:** 2a (blackboard infra) first, then 2b (fan-out + judge).
- **Port depth (2a):** Approach A — faithful-core port. Port the 6 typed notes, the
  deterministic verifier, a deduped + simple-priority digest renderer, Redis store +
  Postgres archive, the NOTE tool, and context injection. **Defer** DeLM's advanced
  lifecycle (FAIL-invalidation, selective unfold, fine-grained token budgeting) until
  2b proves it is needed.

### DeLM references (the source we port from)

- `.references/DeLM/src/shared_lessons.py` — `VALID_TYPES = (FACT, TRIED, OBSERVED,
  FAIL, CLAIM, PATCH_SUMMARY)`; `MAX_CONTENT_CHARS=100`; `MAX_PATCH_SUMMARY_CHARS=300`;
  `note()`, dedup, render/digest logic (~1414 lines — we port the essence, not the
  SWE-bench lifecycle).
- `.references/DeLM/src/verifier.py` — `verify_notes(notes) -> (clean, status)`:
  deterministic hygiene (type normalize/validate, per-type cap, PATCH_SUMMARY
  placeholder-evidence rejection, exact-dup collapse). No LLM.
- `.references/DeLM/src/prompts/note_rules.py` — the NOTE-tool guidance block (per-type
  meaning, sizes, examples, `(none)` convention).

### Reuse from Sub-project 1 (already in the codebase)

- `atria/core/tasks/meta.py` — injectable `redis.asyncio` client pattern, caller-owns
  lifecycle, fakeredis in tests. The blackboard store mirrors this.
- `atria/core/tasks/client.py` `TaskIQClient` — persistent background-loop sync bridge;
  the same approach bridges the synchronous agent loop to async Redis ops.
- Postgres via SQLAlchemy async (session manager) — the archive reuses it.
- `fakeredis` is a dev dependency.

## Goals / Non-goals

**Goals (Phase 2a)**
- A `Blackboard` abstraction (per `task_id`): write verified typed notes, render a
  deduped/prioritized digest, archive on close.
- Deterministic verifier (port of `verify_notes`) — the "verified" guarantee.
- A `NOTE` tool the agent calls to write notes (0–3/turn or `(none)`).
- Context injection of the digest, condition-gated on a blackboard being attached.
- Redis hot path + Postgres archive. No new infrastructure beyond Redis (already
  required by Sub-project 1).
- Independently testable: a single agent can write notes and see its own digest
  rendered back.

**Non-goals (Phase 2a — deferred to 2b or later)**
- `solve_parallel` tool, N-way fan-out, git-worktree isolation, the judge, apply-winner.
- DeLM's advanced lifecycle: FAIL-based patch invalidation, selective unfold, peer-digest
  priority tuning, per-delegation CLAIM caps enforced in storage.
- Any cross-solver coordination (there is one writer in 2a).

## Architecture

A new self-contained package `atria/core/blackboard/`, plus a `NOTE` tool and a
condition-gated prompt section. Sub-project 1 is unchanged.

```
atria/core/blackboard/
  models.py      # NoteType enum, VALID_TYPES, Note dataclass, size caps
  verifier.py    # verify_notes(notes) -> (clean, status)   [pure, no LLM]
  store.py       # BlackboardStore: Redis hot path (per task_id), injectable client, TTL
  archive.py     # archive_to_postgres(task_id, owner_id, notes)
  render.py      # render_digest(notes, viewer_id, window_tokens) -> str   [pure]
  blackboard.py  # Blackboard facade: write/read/render/archive + sync bridge + lifecycle

atria/core/context_engineering/tools/implementations/note_tool.py   # the NOTE tool
  + schema in atria/core/agents/components/schemas/definitions.py
  + handler wiring in atria/core/context_engineering/tools/registry.py
prompt section "Shared Lessons" (PromptComposer, condition: blackboard attached)
```

**Boundaries:** `store` knows only Redis + serialization; `verifier` and `render` are
pure (list→list / notes→string, no I/O); `blackboard.py` is the only composer and owns
the sync/async bridge + lifecycle. Each unit is independently unit-testable.

## Components

### `models.py`
- `NoteType` enum / `VALID_TYPES = ("FACT","TRIED","OBSERVED","FAIL","CLAIM","PATCH_SUMMARY")`.
- `Note` dataclass: `type: str`, `content: str`, `thread_id: int`, `ts: float`.
- Caps: `MAX_CONTENT_CHARS = 100`, `MAX_PATCH_SUMMARY_CHARS = 300`.
- PATCH_SUMMARY content uses `files=… | idea=… | evidence=… | risk=…`.

### `verifier.py` (pure, ported from DeLM)
`verify_notes(notes: list[dict]) -> tuple[list[dict], str]`:
- Uppercase + validate `type` (must be in `VALID_TYPES`); drop invalid.
- Drop empty content; trim to the per-type cap (`MAX_PATCH_SUMMARY_CHARS` for
  PATCH_SUMMARY else `MAX_CONTENT_CHARS`).
- Reject PATCH_SUMMARY whose `evidence=` is missing/empty or a placeholder
  (`tbd, pending, not verified, should work, should pass, looks right, seems to work,
  n/a, …` — port DeLM's `_INVALID_EVIDENCE_PHRASES`).
- Collapse exact `(type, content)` duplicates within the batch.
- Return `(clean, status)` where status is `ok:{kept}/{seen}`. Never raises.

### `store.py`
`BlackboardStore(redis, task_id, ttl)` (injectable async redis client; caller owns it):
- `append(notes: list[Note]) -> None` — RPUSH JSON to `atria:bb:{task_id}`, refresh TTL.
- `read_all() -> list[Note]` — LRANGE + JSON parse.
- Key prefix `atria:bb:`. TTL default 3600s (config).
- Mirrors `atria/core/tasks/meta.py` exactly (no aclose of injected client).

### `render.py` (pure)
`render_digest(notes, viewer_id, window_tokens) -> str`:
- Dedup exact `(type, content)`.
- Priority order: PATCH_SUMMARY > CLAIM > FAIL > FACT > OBSERVED > TRIED.
- Within priority, newest-first; accumulate until `window_tokens` (`~4 chars/token`,
  per-entry overhead ~25 chars per DeLM) is reached; drop the rest.
- Format each entry `[t{thread_id}/{TYPE}] {content}`; join with newlines. Empty notes →
  empty string. (DeLM's selective-unfold / invalidation NOT ported.)

### `archive.py`
`archive_to_postgres(task_id, owner_id, notes) -> None`:
- Insert rows into a new `blackboard_notes` table
  (`id, task_id, owner_id, thread_id, type, content, ts`) via the existing SQLAlchemy
  async session. Best-effort; failures are logged and swallowed. Read-only afterward.

### `blackboard.py`
`Blackboard` facade (one per run's `task_id`):
- `write(thread_id, raw_notes) -> str` → `verify_notes` → `store.append(clean)`; returns status.
- `render(viewer_id) -> str` → `store.read_all` → `render_digest`.
- `archive() -> None` → `archive_to_postgres(read_all())`.
- Owns the sync bridge: when called from the synchronous agent loop, wrap async store
  ops via a persistent background loop (reuse Sub-project 1's `TaskIQClient` loop
  pattern); inside async TaskIQ workers (2b) calls are awaited directly.

### `note_tool.py` + wiring
- Tool `NOTE`: body is up to 3 lines `<TYPE> <content>` (or the literal `(none)`).
- Parses lines → `[{type, content}]`; calls `blackboard.write(thread_id, parsed)`;
  returns the verifier status (e.g. `ok:2/3`).
- Tool description = a port of DeLM's `note_rules` block (per-type meaning, size limits,
  examples, `(none)` convention).
- Registered in the tool registry; **available only when a blackboard is attached** to
  the run.

### Context injection
- A `PromptComposer` section "Shared Lessons", condition-gated on a blackboard being
  attached, that injects `blackboard.render(viewer_id)` before each LLM call. In 2a the
  viewer sees its own accumulated notes; in 2b the same call surfaces peers' notes.

### Config
- A dedicated `BlackboardConfig` (Pydantic, mirroring `BusConfig`/`TasksConfig` in
  `atria/models/config.py`) with `redis_url` (default `redis://localhost:6379/0`),
  `ttl` (default 3600), and `window_tokens` (default 2000); attached to `AppConfig` as
  `blackboard: BlackboardConfig`.

## Data flow

**Write (agent emits NOTE):** tool body → parse lines → `Blackboard.write` →
`verify_notes` → `store.append` → status returned to the agent.

**Read (digest each turn):** "Shared Lessons" section → `Blackboard.render(viewer_id)` →
`store.read_all` → `render_digest` (dedup/priority/budget) → injected into context.

**Lifecycle:** `Blackboard(task_id)` created when parallel mode is active (2b) or behind a
flag in 2a; `archive()` on run completion flushes notes to Postgres; the Redis key
TTL-expires.

## Error handling

- Redis down on write → `NOTE` returns soft failure (`status: "blackboard unavailable"`);
  the run continues. The blackboard is an accelerant, never a hard dependency.
- Redis down on render → empty digest injected; run proceeds.
- Malformed note lines → dropped by `verify_notes` (reflected in the status); never raises.
- Archive failure (Postgres down) → logged and swallowed (inspection only).
- Over-budget digest → `render_digest` truncates to `window_tokens`, priority-then-newest;
  logs the dropped count (no silent full-coverage claim).

## Testing

Per project rule: unit tests AND a real end-to-end run with `OPENAI_API_KEY`.

**Unit (no infra / fakeredis):**
- `verify_notes`: type normalize, per-type cap, placeholder-evidence rejection, dedup,
  status string.
- `render_digest`: dedup, priority order, token-budget truncation, empty input.
- `BlackboardStore`: append/read roundtrip against fakeredis.
- `Blackboard` facade: write→verify→store→render roundtrip (fakeredis); graceful
  degradation when the redis client raises.
- `NOTE` tool: parses a multi-line body, writes verified notes, returns status; `(none)`
  writes nothing.
- `archive_to_postgres`: writes the expected rows (test session / monkeypatched session).

**End-to-end (real, server mode):** attach a blackboard to a run with `OPENAI_API_KEY`;
have the agent emit NOTEs across turns; confirm the digest appears in its next-turn
context and the notes archive to Postgres.

## Forward hooks for Phase 2b

- `Blackboard.render(viewer_id)` already takes a viewer id — in 2b each solver passes its
  own `thread_id` and sees peers' notes.
- The PATCH_SUMMARY note (verified evidence) is the candidate-solution signal the judge
  consumes in 2b.
- `solve_parallel(task, n)` will create one `Blackboard(task_id)`, fan out N background
  subagents (Sub-project 1) each in a git worktree with the blackboard attached, then run
  the judge over their PATCH_SUMMARYs + worktree diffs and apply the winner.
- DeLM's deferred lifecycle (FAIL-invalidation, selective unfold) can be layered into
  `render.py`/`verifier.py` if 2b shows the digest is too noisy.
