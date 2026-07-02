# Maintenance Copilot — Phase 4: Validation, Guardrails & Synthesis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the advisory decision-support layer — grounded LLM answer synthesis with mandatory-citation post-validation, confidence thresholds, an advisory-only framing, an audit trail, and the `validate` / `recommend-refs` / `check` commands.

**Architecture:** Two pure foundation modules — `guardrails.py` (citation enforcement, confidence thresholds, advisory disclaimer) and `audit.py` (append-only JSONL trail with an injectable clock) — then `synthesis.py` (grounded answer + post-validation) wired into `query --synthesize`, and the `validate`/`recommend-refs`/`check` CLI handlers over the Phase-2 index store and Phase-3 graph store. Every LLM answer is post-validated so uncited sentences are dropped; every advisory action is logged. Nothing here issues a dispatch decision — output is always advisory.

**Tech Stack:** Phase 1 `RoleClient` (`synthesis` role) + `config`; Phase 2 `index_store`; Phase 3 `graph_store`; Python stdlib only for guardrails/audit (`re`, `json`, `datetime`). No new external dependency.

**Spec:** `docs/superpowers/specs/2026-07-02-maintenance-copilot-design.md` (§5 commands, §6 guardrails, §4.5 audit)
**Builds on:** Phases 1–3 (config, client, corpus, chunking, index_store, extraction, graph_store, CLI) — all committed on `design/maintenance-copilot`.

## Global Constraints

- Line length ≤ 100 (verify with `uvx ruff check ...` AND `awk 'length>100{print FILENAME":"NR}'` — Ruff's default select does not flag E501 in this repo). Type hints; Google-style docstrings; builtin generics (`list`/`dict`/`X | None`), not `typing.List/Dict/Optional` (`Callable` from typing is fine).
- Tests run with `uv run pytest`. Module tests live at `tests/test_maintenance_copilot_*.py`, load module files via `importlib`, and register each loaded module in `sys.modules` under a unique sentinel name immediately after `module_from_spec`.
- Module scripts add `sys.path.insert(0, str(Path(__file__).resolve().parent))` before sibling imports.
- Module-local only — no imports from `atria/`.
- Tests must NOT hit the network, a DB, or the real clock: inject `chat_fn`, `run_fn`/fake stores, and a `now_fn`. Use a real in-memory Qdrant (`QdrantClient(":memory:")`) for store-backed command tests.
- **Advisory-only is non-negotiable:** no command may emit an approval or dispatch verdict. Every synthesized answer carries the advisory disclaimer; low-confidence results are marked `needs_review` and not presented as settled.
- **Mandatory citation:** any synthesized sentence without a citation marker resolving to a retrieved chunk is dropped from the answer (kept in a `dropped` list for transparency).
- Audit state lives under the module `data/` dir (gitignored); tests point `MC_AUDIT_LOG` at a temp path.
- Commits must NOT include a `Co-Authored-By: Claude` trailer.
- Branch: `design/maintenance-copilot` (already checked out). Do not create branches.

---

### Task 1: Guardrails — citation enforcement, confidence, disclaimer

**Files:**
- Create: `modules/maintenance_copilot/scripts/guardrails.py`
- Test: `tests/test_maintenance_copilot_guardrails.py`

**Interfaces:**
- Produces:
  - `ADVISORY_NOTE: str` — the fixed advisory-only disclaimer.
  - `default_min_confidence() -> float` — reads `MC_MIN_CONFIDENCE` (float), default `0.35`.
  - `split_sentences(text: str) -> list[str]` — split on sentence boundaries (`.`/`!`/`?` + space/newline), dropping empties.
  - `enforce_citations(answer: str, allowed: set[str]) -> dict` — returns `{"answer": <grounded joined>, "grounded": [...], "dropped": [...]}`. A sentence is grounded iff it contains a `[marker]` whose inner text is in `allowed`.
  - `answer_confidence(hits: list[dict]) -> float` — the top hit's `score` (0.0 if no hits).
  - `needs_manual_review(confidence: float, grounded_count: int, min_confidence: float | None = None) -> bool` — True when `confidence < min` OR `grounded_count == 0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_guardrails.py
"""Tests for the guardrails: citation enforcement, confidence, review routing."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


def test_enforce_citations_drops_uncited_sentences():
    g = _load("guardrails", "mc_guardrails_uut")
    answer = (
        "The main gear pivot pin torque is 1200 in-lb [amm_ata32#1]. "
        "The aircraft can always be dispatched with the gear removed. "
        "MEL 32-30-01 is Category C [mel_ata32#0]."
    )
    out = g.enforce_citations(answer, {"amm_ata32#1", "mel_ata32#0"})
    assert len(out["grounded"]) == 2
    assert len(out["dropped"]) == 1
    assert "always be dispatched" in out["dropped"][0]
    assert "[amm_ata32#1]" in out["answer"]


def test_enforce_citations_marker_not_in_allowed_is_dropped():
    g = _load("guardrails", "mc_guardrails_uut2")
    out = g.enforce_citations("Fabricated claim [ghost#9].", {"amm_ata32#1"})
    assert out["grounded"] == []
    assert len(out["dropped"]) == 1


def test_confidence_and_review_routing():
    g = _load("guardrails", "mc_guardrails_uut3")
    assert g.answer_confidence([{"score": 0.8}, {"score": 0.2}]) == 0.8
    assert g.answer_confidence([]) == 0.0
    # Below default threshold OR nothing grounded → needs review.
    assert g.needs_manual_review(0.1, grounded_count=3) is True
    assert g.needs_manual_review(0.9, grounded_count=0) is True
    assert g.needs_manual_review(0.9, grounded_count=2) is False


def test_min_confidence_env_override(monkeypatch):
    g = _load("guardrails", "mc_guardrails_uut4")
    monkeypatch.setenv("MC_MIN_CONFIDENCE", "0.7")
    assert g.default_min_confidence() == 0.7
    assert g.needs_manual_review(0.6, grounded_count=5) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_guardrails.py -v`
Expected: FAIL — `guardrails.py` does not exist.

- [ ] **Step 3: Write `guardrails.py`**

```python
# modules/maintenance_copilot/scripts/guardrails.py
"""Advisory guardrails: mandatory citation, confidence thresholds, disclaimer.

These are enforced in code, not left to the prompt: a synthesized answer has
its uncited sentences stripped, and low-confidence results are routed for
manual review rather than presented as settled. Output is always advisory.
"""

from __future__ import annotations

import os
import re

ADVISORY_NOTE = (
    "ADVISORY ONLY — this is decision support, not a dispatch decision. "
    "A licensed engineer must verify every cited reference and sign off. "
    "Dispatch is never automated."
)

_DEFAULT_MIN_CONFIDENCE = 0.35
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]+", re.DOTALL)
_MARKER_RE = re.compile(r"\[([^\[\]]+?)\]")


def default_min_confidence() -> float:
    """Return the confidence floor from MC_MIN_CONFIDENCE, else 0.35."""
    raw = os.environ.get("MC_MIN_CONFIDENCE")
    if raw is None:
        return _DEFAULT_MIN_CONFIDENCE
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_MIN_CONFIDENCE


def split_sentences(text: str) -> list[str]:
    """Split text into sentences on ``.``/``!``/``?`` boundaries."""
    out = [m.group(0).strip() for m in _SENTENCE_RE.finditer(text)]
    return [s for s in out if s]


def enforce_citations(answer: str, allowed: set[str]) -> dict:
    """Keep only sentences carrying a citation marker resolving to a chunk.

    Args:
        answer: The raw synthesized answer.
        allowed: The set of valid citation keys (retrieved chunk ids).

    Returns:
        ``{"answer","grounded","dropped"}`` — grounded sentences joined, plus
        the grounded and dropped sentence lists.
    """
    grounded: list[str] = []
    dropped: list[str] = []
    for sentence in split_sentences(answer):
        markers = {m.strip() for m in _MARKER_RE.findall(sentence)}
        if markers & allowed:
            grounded.append(sentence)
        else:
            dropped.append(sentence)
    return {"answer": " ".join(grounded), "grounded": grounded, "dropped": dropped}


def answer_confidence(hits: list[dict]) -> float:
    """Confidence proxy: the top hit's score (0.0 when there are no hits)."""
    if not hits:
        return 0.0
    return float(hits[0].get("score", 0.0))


def needs_manual_review(
    confidence: float, grounded_count: int, min_confidence: float | None = None
) -> bool:
    """True when confidence is below the floor or nothing was grounded."""
    floor = default_min_confidence() if min_confidence is None else min_confidence
    return confidence < floor or grounded_count == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_guardrails.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add modules/maintenance_copilot/scripts/guardrails.py \
        tests/test_maintenance_copilot_guardrails.py
git commit -m "feat(maintenance_copilot): advisory guardrails — citation enforcement + confidence"
```

---

### Task 2: Audit trail (append-only JSONL, injectable clock)

**Files:**
- Create: `modules/maintenance_copilot/scripts/audit.py`
- Test: `tests/test_maintenance_copilot_audit.py`

**Interfaces:**
- Produces:
  - `default_log_path() -> str` — `MC_AUDIT_LOG` if set, else `<module>/data/audit.log.jsonl`.
  - `append_event(event: dict, path: str | None = None, now_fn=None) -> dict` — stamps `ts` (ISO-8601 UTC via `now_fn`, default `datetime.now(timezone.utc)`), appends one JSON line, returns the stamped event. Creates parent dirs.
  - `read_events(path: str | None = None) -> list[dict]` — parse the JSONL back (empty list if the file is absent).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_audit.py
"""Tests for the append-only JSONL audit trail with an injectable clock."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


def _fixed_now():
    return datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


def test_append_then_read_roundtrip(tmp_path):
    a = _load("audit", "mc_audit_uut")
    log = str(tmp_path / "audit.log.jsonl")
    a.append_event({"type": "query", "text": "gear"}, path=log, now_fn=_fixed_now)
    a.append_event({"type": "recommend", "text": "brake"}, path=log, now_fn=_fixed_now)
    events = a.read_events(log)
    assert [e["type"] for e in events] == ["query", "recommend"]
    assert events[0]["ts"] == "2026-07-02T12:00:00+00:00"
    assert events[0]["text"] == "gear"


def test_read_missing_file_is_empty(tmp_path):
    a = _load("audit", "mc_audit_uut2")
    assert a.read_events(str(tmp_path / "nope.jsonl")) == []


def test_append_stamps_ts_and_returns_event(tmp_path):
    a = _load("audit", "mc_audit_uut3")
    log = str(tmp_path / "sub" / "audit.jsonl")   # parent dir must be created
    out = a.append_event({"type": "confirm"}, path=log, now_fn=_fixed_now)
    assert out["ts"] == "2026-07-02T12:00:00+00:00"
    assert Path(log).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_audit.py -v`
Expected: FAIL — `audit.py` does not exist.

- [ ] **Step 3: Write `audit.py`**

```python
# modules/maintenance_copilot/scripts/audit.py
"""Append-only JSONL audit trail for advisory actions.

Every query, recommendation, validation, and engineer confirmation is appended
with a UTC timestamp so an AI-suggested reference can be traced to the exact
document/revision/page used — the regulatory-traceability requirement.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import os

_LOG_NAME = "audit.log.jsonl"


def default_log_path() -> str:
    """Return MC_AUDIT_LOG if set, else ``<module>/data/audit.log.jsonl``."""
    override = os.environ.get("MC_AUDIT_LOG")
    if override:
        return override
    return str(Path(__file__).resolve().parent.parent / "data" / _LOG_NAME)


def append_event(event: dict, path: str | None = None,
                 now_fn: Callable[[], datetime] | None = None) -> dict:
    """Stamp ``event`` with a UTC ``ts`` and append it as one JSON line.

    Args:
        event: The event payload (not mutated; a stamped copy is written).
        path: Log path; defaults to :func:`default_log_path`.
        now_fn: Clock returning an aware datetime; defaults to ``now(utc)``.

    Returns:
        The stamped event that was written.
    """
    target = Path(path or default_log_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    clock = now_fn or (lambda: datetime.now(timezone.utc))
    stamped = {"ts": clock().isoformat(), **event}
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped, ensure_ascii=False) + "\n")
    return stamped


def read_events(path: str | None = None) -> list[dict]:
    """Read the JSONL log back into a list (empty if the file is absent)."""
    target = Path(path or default_log_path())
    if not target.is_file():
        return []
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_audit.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add modules/maintenance_copilot/scripts/audit.py \
        tests/test_maintenance_copilot_audit.py
git commit -m "feat(maintenance_copilot): append-only JSONL audit trail"
```

---

### Task 3: Grounded answer synthesis + `query --synthesize`

**Files:**
- Create: `modules/maintenance_copilot/scripts/synthesis.py`
- Modify: `modules/maintenance_copilot/scripts/copilot.py` (`query` gains `--synthesize`; `_cmd_query` composes + audits an answer)
- Test: `tests/test_maintenance_copilot_synthesis.py`, `tests/test_maintenance_copilot_query_synth_cli.py`

**Interfaces:**
- Consumes: `guardrails` (Task 1), `audit` (Task 2).
- Produces:
  - `build_synthesis_messages(query: str, hits: list[dict]) -> list[dict]` — system instructs: answer ONLY from the passages, cite each claim with `[<chunk_id>]`, never invent; user lists each hit as `[<chunk_id>] <text>`.
  - `synthesize(query: str, hits: list[dict], chat_fn) -> dict` — calls `chat_fn(messages)`, runs `enforce_citations` against the hit chunk_ids, computes confidence + review routing, returns:
    `{"answer","dropped","confidence","needs_review","disclaimer","citations":[chunk_ids kept]}`. When `needs_review` is True, `answer` is replaced by a manual-review notice (the grounded text is still available under `grounded`).
  - `copilot.py` `_cmd_query(..., with_graph=False, synthesize=False)` — when `synthesize`, attaches `"answer"` (the `synthesize(...)` dict) to the payload and appends an audit event `{"type":"query","query":...,"citations":[...],"needs_review":...}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_maintenance_copilot_synthesis.py
"""Tests for grounded answer synthesis + citation post-validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name, sentinel):
    spec = importlib.util.spec_from_file_location(sentinel, _MOD / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[sentinel] = mod
    spec.loader.exec_module(mod)
    return mod


_HITS = [
    {"chunk_id": "amm_ata32#1", "text": "Torque the pivot pin nut to 1200 in-lb.",
     "citation": "AMM ... · amm_ata32#1", "score": 0.9},
    {"chunk_id": "mel_ata32#0", "text": "MEL 32-30-01 Category C.",
     "citation": "MEL ... · mel_ata32#0", "score": 0.8},
]


def test_synthesize_keeps_cited_drops_uncited():
    syn = _load("synthesis", "mc_synth_uut")

    def fake_chat(messages):
        return ("Torque is 1200 in-lb [amm_ata32#1]. "
                "You may always dispatch with the gear removed.")

    out = syn.synthesize("gear torque?", _HITS, fake_chat)
    assert "1200 in-lb" in out["answer"]
    assert "always dispatch" not in out["answer"]
    assert out["dropped"] and "always dispatch" in out["dropped"][0]
    assert out["citations"] == ["amm_ata32#1"]
    assert out["needs_review"] is False
    assert "ADVISORY ONLY" in out["disclaimer"]


def test_synthesize_low_confidence_flags_review():
    syn = _load("synthesis", "mc_synth_uut2")
    low = [{"chunk_id": "amm_ata32#1", "text": "x", "citation": "c", "score": 0.05}]

    def fake_chat(messages):
        return "Torque is 1200 in-lb [amm_ata32#1]."

    out = syn.synthesize("q", low, fake_chat)
    assert out["needs_review"] is True
    assert "review" in out["answer"].lower()


def test_synthesize_all_uncited_flags_review():
    syn = _load("synthesis", "mc_synth_uut3")

    def fake_chat(messages):
        return "Unicorns fix landing gear."

    out = syn.synthesize("q", _HITS, fake_chat)
    assert out["needs_review"] is True
    assert out["citations"] == []
```

```python
# tests/test_maintenance_copilot_query_synth_cli.py
"""Tests for `query --synthesize` wiring (in-memory Qdrant, fake chat, temp audit)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_query_synth_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_query_synth_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    return [[1.0 if "gear" in t.lower() else 0.0, 0.0, 0.0] for t in texts]


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    mod = _load_cli()
    from qdrant_client import QdrantClient
    shared = QdrantClient(":memory:")
    monkeypatch.setenv("MC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

    def fake_store(embed_fn=None, qdrant=None):
        s = mod.IndexStore(shared, _embed_fn)
        s.ensure_collection(dim=3)
        return s

    monkeypatch.setattr(mod, "_build_store", fake_store)
    monkeypatch.setattr(mod, "_synthesis_chat_fn",
                        lambda: (lambda messages: "Gear removal per AMM [amm_ata32#0]."))
    return mod, str(tmp_path / "audit.jsonl")


def test_query_synthesize_attaches_answer_and_audits(cli, capsys):
    mod, audit_log = cli
    mod.main(["ingest"])
    capsys.readouterr()
    rc = mod.main(["query", "gear removal", "--revision", "none", "--synthesize"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "answer" in out
    assert "disclaimer" in out["answer"]
    # An audit event was recorded.
    from importlib import import_module  # noqa: F401
    lines = Path(audit_log).read_text(encoding="utf-8").splitlines()
    assert any(json.loads(ln)["type"] == "query" for ln in lines)


def test_query_without_synthesize_has_no_answer(cli, capsys):
    mod, _ = cli
    mod.main(["ingest"])
    capsys.readouterr()
    mod.main(["query", "gear", "--revision", "none"])
    out = json.loads(capsys.readouterr().out)
    assert "answer" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_maintenance_copilot_synthesis.py tests/test_maintenance_copilot_query_synth_cli.py -v`
Expected: FAIL — `synthesis.py` and `_synthesis_chat_fn`/`--synthesize` do not exist.

- [ ] **Step 3: Write `synthesis.py`**

```python
# modules/maintenance_copilot/scripts/synthesis.py
"""Compose a cited answer grounded ONLY in retrieved passages.

The LLM is asked to cite every claim with the passage's ``[chunk_id]``; the
result is then post-validated — any sentence without a citation resolving to a
retrieved chunk is dropped, and low-confidence answers are routed for review.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guardrails import (  # type: ignore[import-not-found]
    ADVISORY_NOTE,
    answer_confidence,
    enforce_citations,
    needs_manual_review,
)

_REVIEW_NOTICE = (
    "Insufficient grounded evidence — routed for mandatory manual review. "
    "See the retrieved passages and verify against the approved manuals."
)


def build_synthesis_messages(query: str, hits: list[dict]) -> list[dict]:
    """Build chat messages that force passage-grounded, cited answers."""
    system = (
        "You answer aircraft-maintenance questions using ONLY the provided "
        "passages. Cite every claim with the passage tag in square brackets, "
        "e.g. [amm_ata32#1]. Do not use outside knowledge. If the passages do "
        "not answer the question, say so. Never state a dispatch decision."
    )
    passages = "\n".join(f"[{h['chunk_id']}] {h['text']}" for h in hits)
    user = f"Question: {query}\n\nPassages:\n{passages}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def synthesize(query: str, hits: list[dict], chat_fn: Callable[[list], str]) -> dict:
    """Synthesize a cited answer and post-validate it against the hits.

    Args:
        query: The user question.
        hits: Retrieved passages (each with ``chunk_id``, ``text``, ``score``).
        chat_fn: Callable taking chat messages, returning the raw answer string.

    Returns:
        ``{"answer","grounded","dropped","confidence","needs_review",
        "disclaimer","citations"}``.
    """
    raw = chat_fn(build_synthesis_messages(query, hits))
    allowed = {h["chunk_id"] for h in hits}
    checked = enforce_citations(raw, allowed)
    confidence = answer_confidence(hits)
    review = needs_manual_review(confidence, len(checked["grounded"]))
    citations = [c for c in allowed if f"[{c}]" in checked["answer"]]
    answer = _REVIEW_NOTICE if review else checked["answer"]
    return {
        "answer": answer,
        "grounded": checked["grounded"],
        "dropped": checked["dropped"],
        "confidence": confidence,
        "needs_review": review,
        "disclaimer": ADVISORY_NOTE,
        "citations": sorted(citations),
    }
```

- [ ] **Step 4: Wire `--synthesize` into `copilot.py`**

Add the sibling audit import (after existing ones). Do NOT import `synthesize` at
module top — the `synthesize_answer` helper imports it locally under an alias to
avoid clashing with the `synthesize` bool parameter:

```python
import audit  # type: ignore[import-not-found]
```

Add a chat-fn builder near `_kg_chat_fn`:

```python
def _synthesis_chat_fn():
    """Return a chat callable bound to the synthesis role."""
    rc = RoleClient(load_config())
    return lambda messages: rc.chat("synthesis", messages)
```

Replace `_cmd_query` with the synthesize-aware version (keeps prior behavior when `synthesize=False`):

```python
def _cmd_query(text: str, k: int, ata: Optional[str], revision: str,
               with_graph: bool = False, synthesize: bool = False) -> int:
    rev: Optional[str] = None if revision.lower() == "none" else revision
    store = _build_store()
    hits = store.query(text, k=k, ata_chapter=ata, revision=rev)
    payload: dict[str, object] = {"query": text, "hits": hits}
    if with_graph and hits:
        chapter = ata or hits[0].get("ata_chapter")
        related = _build_graph_store().neighbors(chapter, hops=1) if chapter else []
        payload["graph_context"] = {"ata_chapter": chapter, "related": related}
    if synthesize:
        answer = synthesize_answer(text, hits)
        payload["answer"] = answer
        audit.append_event({"type": "query", "query": text,
                            "citations": answer["citations"],
                            "needs_review": answer["needs_review"]})
    print(json.dumps(payload, indent=2))
    return 0


def synthesize_answer(text: str, hits: list) -> dict:
    """Synthesize a cited answer for ``text`` over ``hits`` via the synthesis role."""
    from synthesis import synthesize as _synth  # local alias to avoid shadowing

    return _synth(text, hits, _synthesis_chat_fn())
```

(Note: the sibling `from synthesis import synthesize` at module top and the
`synthesize` bool parameter share a name; the handler calls the module function
through the `synthesize_answer` helper, which imports it under a local alias, so
there is no shadow. Do NOT also keep the top-level `from synthesis import
synthesize` import — remove it to avoid the name clash; `synthesize_answer` owns
the import.)

Add the flag to the `query` subparser:

```python
    p_query.add_argument("--synthesize", action="store_true",
                         help="Compose a cited answer (needs the synthesis LLM).")
```

Update the `query` dispatch branch:

```python
    if args.command == "query":
        return _cmd_query(args.text, args.k, args.ata, args.revision,
                          args.graph, args.synthesize)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_maintenance_copilot_synthesis.py tests/test_maintenance_copilot_query_synth_cli.py -v`
Expected: PASS (3 + 2).

- [ ] **Step 6: Full suite + lint**

Run: `uv run pytest tests/test_maintenance_copilot_*.py -v` → all pass.
Run: `uvx ruff check modules/maintenance_copilot tests/test_maintenance_copilot_*.py` → clean.
Run: `awk 'length>100{print FILENAME":"NR}' modules/maintenance_copilot/scripts/*.py` → no output.

- [ ] **Step 7: Commit**

```bash
git add modules/maintenance_copilot/scripts/synthesis.py \
        modules/maintenance_copilot/scripts/copilot.py \
        tests/test_maintenance_copilot_synthesis.py \
        tests/test_maintenance_copilot_query_synth_cli.py
git commit -m "feat(maintenance_copilot): grounded answer synthesis + query --synthesize"
```

---

### Task 4: `validate` and `recommend-refs` commands

**Files:**
- Modify: `modules/maintenance_copilot/scripts/copilot.py`
- Test: `tests/test_maintenance_copilot_validate_cli.py`

**Interfaces:**
- Consumes: `_build_store` (Phase 2), `audit` (Task 2).
- Produces (additions to `copilot.py`):
  - `_read_json_arg(value: str) -> dict` — parse a JSON string, or read from stdin when `value == "-"`.
  - `_cmd_recommend_refs(text: str, k: int) -> int` — retrieval top-k → prints `{"query","recommendations":[{"citation","chunk_id","doc_type","revision","confidence"}]}`; audits `{"type":"recommend","query":...,"citations":[...]}`. `confidence` = hit `score`.
  - `_cmd_validate(raw: str) -> int` — input `{"defect": str, "cited_refs": [str,...]}`. For each ref, `store.query(ref, k=3, revision="current")`; a ref `"pass"`es if a hit's `citation` or `text` contains the ref's identifier token (case-insensitive), attaching that hit's citation as `support`, else `"fail"`. Prints `{"defect","results":[{"ref","status","support"}]}`; audits `{"type":"validate","refs":[...],"results":[...]}`.
  - Subparsers `recommend-refs "<text>" [--k]` and `validate <json|->`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_validate_cli.py
"""Tests for `recommend-refs` and `validate` (in-memory Qdrant, temp audit)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_validate_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_validate_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _embed_fn(texts):
    out = []
    for t in texts:
        low = t.lower()
        out.append([1.0 if "gear" in low or "32" in low else 0.0,
                    1.0 if "door" in low or "52" in low else 0.0, 0.0])
    return out


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    mod = _load_cli()
    from qdrant_client import QdrantClient
    shared = QdrantClient(":memory:")
    monkeypatch.setenv("MC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))

    def fake_store(embed_fn=None, qdrant=None):
        s = mod.IndexStore(shared, _embed_fn)
        s.ensure_collection(dim=3)
        return s

    monkeypatch.setattr(mod, "_build_store", fake_store)
    return mod


def test_recommend_refs_ranks_and_audits(cli, capsys, tmp_path):
    cli.main(["ingest"])
    capsys.readouterr()
    rc = cli.main(["recommend-refs", "landing gear removal", "--k", "3"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["query"] == "landing gear removal"
    assert len(out["recommendations"]) >= 1
    assert all("citation" in r and "confidence" in r for r in out["recommendations"])
    log = Path(str(tmp_path / "audit.jsonl")).read_text().splitlines()
    assert any(json.loads(x)["type"] == "recommend" for x in log)


def test_validate_marks_missing_ref_fail(cli, capsys):
    cli.main(["ingest"])
    capsys.readouterr()
    payload = json.dumps({"defect": "gear indicator inop",
                          "cited_refs": ["MEL 32-30-01", "AMM 99-99-99"]})
    rc = cli.main(["validate", payload])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    by_ref = {r["ref"]: r for r in out["results"]}
    assert by_ref["MEL 32-30-01"]["status"] == "pass"
    assert by_ref["MEL 32-30-01"]["support"]
    assert by_ref["AMM 99-99-99"]["status"] == "fail"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_validate_cli.py -v`
Expected: FAIL — no `recommend-refs`/`validate` subcommands.

- [ ] **Step 3: Extend `copilot.py`**

Add helpers + handlers:

```python
def _read_json_arg(value: str) -> dict:
    """Parse a JSON string, or read JSON from stdin when value == '-'."""
    if value == "-":
        value = sys.stdin.read()
    return json.loads(value)


def _cmd_recommend_refs(text: str, k: int) -> int:
    store = _build_store()
    hits = store.query(text, k=k, revision="current")
    recs = [
        {"citation": h["citation"], "chunk_id": h["chunk_id"], "doc_type": h["doc_type"],
         "revision": h["revision"], "confidence": h["score"]}
        for h in hits
    ]
    audit.append_event({"type": "recommend", "query": text,
                        "citations": [r["chunk_id"] for r in recs]})
    print(json.dumps({"query": text, "recommendations": recs}, indent=2))
    return 0


def _cmd_validate(raw: str) -> int:
    data = _read_json_arg(raw)
    store = _build_store()
    results = []
    for ref in data.get("cited_refs", []):
        token = ref.split()[-1].lower() if ref.split() else ref.lower()
        hits = store.query(ref, k=3, revision="current")
        support = None
        for h in hits:
            if token in h["citation"].lower() or token in h["text"].lower():
                support = h["citation"]
                break
        results.append({"ref": ref, "status": "pass" if support else "fail",
                        "support": support})
    audit.append_event({"type": "validate", "refs": data.get("cited_refs", []),
                        "results": results})
    print(json.dumps({"defect": data.get("defect", ""), "results": results}, indent=2))
    return 0
```

Add subparsers:

```python
    p_rec = sub.add_parser("recommend-refs", help="Rank AMM/MEL/CDL/TSM refs for a defect.")
    p_rec.add_argument("text")
    p_rec.add_argument("--k", type=int, default=5)
    p_val = sub.add_parser("validate", help="Validate cited refs against approved docs.")
    p_val.add_argument("payload", help="JSON string, or '-' to read stdin.")
```

Add dispatch branches:

```python
    if args.command == "recommend-refs":
        return _cmd_recommend_refs(args.text, args.k)
    if args.command == "validate":
        return _cmd_validate(args.payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_validate_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest tests/test_maintenance_copilot_*.py -v` → all pass.
Run: `uvx ruff check modules/maintenance_copilot tests/test_maintenance_copilot_*.py` → clean.
Run: `awk 'length>100{print FILENAME":"NR}' modules/maintenance_copilot/scripts/*.py` → no output.

- [ ] **Step 6: Commit**

```bash
git add modules/maintenance_copilot/scripts/copilot.py \
        tests/test_maintenance_copilot_validate_cli.py
git commit -m "feat(maintenance_copilot): validate + recommend-refs commands with audit"
```

---

### Task 5: `check` command — flag inconsistencies (index + graph)

**Files:**
- Modify: `modules/maintenance_copilot/scripts/copilot.py`
- Test: `tests/test_maintenance_copilot_check_cli.py`

**Interfaces:**
- Consumes: `_build_store` (Phase 2), `_build_graph_store` (Phase 3), `audit` (Task 2).
- Produces (additions to `copilot.py`):
  - `_cmd_check(raw: str) -> int` — input `{"defect": str, "cited_mel": str, "dispatch_condition": str, "classification": str}`. Produces `{"defect","inconsistencies":[{"severity","issue","source"}],"advisories":[...]}` and audits `{"type":"check","cited_mel":...,"inconsistencies":[...]}`. Advisory-only; never a verdict. Checks:
    1. **MEL existence** — `store.query(cited_mel, k=3, revision="current")`; if no hit's text/citation contains the MEL id token → inconsistency `severity="high"`, `issue="cited MEL item not found in approved docs"`.
    2. **REQUIRES advisories** — `graph.neighbors(<mel id>, hops=1)`; each neighbor reached by a `REQUIRES` edge becomes an advisory `"ensure <neighbor_key> is satisfied (placard/tooling/interval)"`, tagged with its `status` (so `unverified` links are flagged).
    3. **Category mention** — if `classification` is non-empty and the retrieved MEL text mentions a `Category X` that differs from `classification`, add inconsistency `severity="medium"`, `issue="stated classification <X> differs from cited MEL category <Y>"`.
  - Subparser `check <json|->`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_maintenance_copilot_check_cli.py
"""Tests for the `check` inconsistency-flagging command (fakes; temp audit)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CLI = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "copilot.py"
)


def _load_cli():
    spec = importlib.util.spec_from_file_location("mc_check_uut", _CLI)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_check_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeStore:
    def __init__(self, hits):
        self._hits = hits

    def query(self, text, k=5, ata_chapter=None, revision="current"):
        return self._hits


class _FakeGraph:
    def neighbors(self, key, hops=1):
        return [{"neighbor_key": "PLACARD-32-30-01", "neighbor_labels": ["Part"],
                 "edge_type": "REQUIRES", "status": "unverified", "confidence": 0.8}]


@pytest.fixture()
def cli(monkeypatch, tmp_path):
    mod = _load_cli()
    monkeypatch.setenv("MC_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    return mod, tmp_path


def test_check_flags_missing_mel_and_requires_advisory(cli, capsys, monkeypatch):
    mod, tmp_path = cli
    # MEL not found (empty hits) + a REQUIRES advisory from the graph.
    monkeypatch.setattr(mod, "_build_store", lambda: _FakeStore([]))
    monkeypatch.setattr(mod, "_build_graph_store", lambda run_fn=None: _FakeGraph())
    payload = json.dumps({"defect": "gear indicator inop", "cited_mel": "MEL 32-30-01",
                          "dispatch_condition": "one indicator inop", "classification": ""})
    rc = mod.main(["check", payload])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert any(i["severity"] == "high" for i in out["inconsistencies"])
    assert any("PLACARD-32-30-01" in a["item"] for a in out["advisories"])
    assert out["advisories"][0]["status"] == "unverified"
    log = Path(str(tmp_path / "audit.jsonl")).read_text().splitlines()
    assert any(json.loads(x)["type"] == "check" for x in log)


def test_check_flags_category_mismatch(cli, capsys, monkeypatch):
    mod, _ = cli
    hits = [{"chunk_id": "mel_ata32#0", "text": "MEL 32-30-01 Category C. ...",
             "citation": "MEL ... · mel_ata32#0", "doc_type": "MEL",
             "revision": "Rev-18", "ata_chapter": "32", "score": 0.9}]
    monkeypatch.setattr(mod, "_build_store", lambda: _FakeStore(hits))
    monkeypatch.setattr(mod, "_build_graph_store", lambda run_fn=None: _FakeGraph())
    payload = json.dumps({"defect": "d", "cited_mel": "MEL 32-30-01",
                          "dispatch_condition": "x", "classification": "A"})
    mod.main(["check", payload])
    out = json.loads(capsys.readouterr().out)
    assert any("classification" in i["issue"] and i["severity"] == "medium"
               for i in out["inconsistencies"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_maintenance_copilot_check_cli.py -v`
Expected: FAIL — no `check` subcommand.

- [ ] **Step 3: Extend `copilot.py`**

Add the handler:

```python
def _cmd_check(raw: str) -> int:
    data = _read_json_arg(raw)
    mel = data.get("cited_mel", "")
    mel_token = mel.split()[-1].lower() if mel.split() else mel.lower()
    store = _build_store()
    hits = store.query(mel, k=3, revision="current")
    inconsistencies: list[dict] = []
    advisories: list[dict] = []

    mel_hit = next(
        (h for h in hits if mel_token in h["citation"].lower()
         or mel_token in h["text"].lower()),
        None,
    )
    if mel_hit is None:
        inconsistencies.append({"severity": "high", "source": mel,
                                "issue": "cited MEL item not found in approved docs"})

    classification = (data.get("classification") or "").strip()
    if mel_hit is not None and classification:
        match = re.search(r"Category\s+([A-D])", mel_hit["text"])
        if match and match.group(1).upper() != classification.upper():
            inconsistencies.append({
                "severity": "medium", "source": mel_hit["citation"],
                "issue": f"stated classification {classification} differs from cited "
                         f"MEL category {match.group(1)}",
            })

    if mel_token:
        for row in _build_graph_store().neighbors(mel_token, hops=1):
            if row.get("edge_type") == "REQUIRES":
                advisories.append({
                    "item": row["neighbor_key"], "status": row.get("status"),
                    "note": "ensure required placard/tooling/interval is satisfied",
                })

    audit.append_event({"type": "check", "cited_mel": mel,
                        "inconsistencies": inconsistencies})
    print(json.dumps({"defect": data.get("defect", ""),
                      "inconsistencies": inconsistencies,
                      "advisories": advisories}, indent=2))
    return 0
```

Add `import re` to the top of `copilot.py` if not already present.

Add the subparser:

```python
    p_check = sub.add_parser("check", help="Flag inconsistencies in a defect write-up.")
    p_check.add_argument("payload", help="JSON string, or '-' to read stdin.")
```

Add the dispatch branch:

```python
    if args.command == "check":
        return _cmd_check(args.payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_maintenance_copilot_check_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest tests/test_maintenance_copilot_*.py -v` → all pass.
Run: `uvx ruff check modules/maintenance_copilot tests/test_maintenance_copilot_*.py` → clean.
Run: `awk 'length>100{print FILENAME":"NR}' modules/maintenance_copilot/scripts/*.py` → no output.

- [ ] **Step 6: Commit**

```bash
git add modules/maintenance_copilot/scripts/copilot.py \
        tests/test_maintenance_copilot_check_cli.py
git commit -m "feat(maintenance_copilot): check command flags defect-writeup inconsistencies"
```

- [ ] **Step 7: Real end-to-end (deferred — needs live TEI + Qdrant + LLM)**

Record for a Docker host (not run in CI/sandbox):

```bash
docker compose -f docker-compose.dev.yml up -d tei qdrant neo4j
# LLM: --profile gpu + copilot-llm, or set MC_SYNTHESIS_BASE_URL to a reachable endpoint
docker compose -f docker-compose.dev.yml exec atria \
    python /app/modules/maintenance_copilot/scripts/copilot.py ingest
docker compose -f docker-compose.dev.yml exec atria \
    python /app/modules/maintenance_copilot/scripts/copilot.py query "gear fails to retract" --synthesize
docker compose -f docker-compose.dev.yml exec atria \
    python /app/modules/maintenance_copilot/scripts/copilot.py validate \
      '{"defect":"gear indicator inop","cited_refs":["MEL 32-30-01"]}'
docker compose -f docker-compose.dev.yml exec atria \
    python /app/modules/maintenance_copilot/scripts/copilot.py check \
      '{"defect":"gear indicator inop","cited_mel":"MEL 32-30-01","dispatch_condition":"one inop","classification":"A"}'
```

Expected: `query --synthesize` returns a cited answer + disclaimer (uncited sentences dropped); `validate` passes the real MEL ref; `check` flags the A-vs-C category mismatch; `data/audit.log.jsonl` gains one line per action.

---

## Phase 4 self-review

- **Spec coverage (Phase 4 slice):** LLM answer synthesis grounded in retrieved chunks (spec §5 query) → Task 3; mandatory citation post-validation + confidence thresholds + advisory framing (spec §6) → Tasks 1 + 3; audit trail (spec §4.5) → Task 2 + wired into Tasks 3–5; `validate` / `recommend-refs` (spec §5) → Task 4; `check` inconsistency flagging (spec §5) → Task 5. Not in this phase: graph multi-hop hardening, the dashboard (Phase 5).
- **Placeholder scan:** none — every step ships runnable code or an exact command.
- **Type consistency:** `enforce_citations`/`answer_confidence`/`needs_manual_review`/`ADVISORY_NOTE` (Task 1) are consumed by `synthesize` (Task 3); `audit.append_event` (Task 2) is called by Tasks 3–5; `_build_store`/`_build_graph_store` (Phases 2–3) are consumed by Tasks 4–5; `_read_json_arg` (Task 4) is reused by Task 5; `synthesize_answer`/`_synthesis_chat_fn` names match between `copilot.py` and the CLI test.
- **Known decisions / limitations (for the reviewer):**
  - Confidence is a proxy (top hit score); a real calibrated confidence is out of scope for the pilot.
  - `validate`/`check` "reference exists" is a substring match of the ref's last token against retrieved citations/text — adequate for the synthetic corpus; a structured ref index is Phase-5+ hardening.
  - Sentence splitting is regex-based (no NLP dependency); citation markers must be `[chunk_id]` exactly. The synthesis prompt instructs this, but a non-conforming LLM will have more sentences dropped — which is the safe failure mode (drop, don't fabricate).
  - There is a name overlap between the `synthesize` bool param and the imported `synthesize` function; Task 3 resolves it by routing through `synthesize_answer` (local aliased import) and NOT keeping a top-level `from synthesis import synthesize`. The reviewer should confirm no shadow remains.

## Roadmap — remaining phase (its own plan)

- **Phase 5 — Dashboard:** Query / Graph / Audit tabs on `dashboard.html` via the module bridge (the audit tab reads `data/audit.log.jsonl` through `audit.read_events`).
