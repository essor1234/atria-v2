"""Deterministic note hygiene — type-normalize, cap, dedupe. No LLM, never raises.

This is the cheap *pre-gate*. Semantic admission — checking that a note's claim is
grounded and non-speculative (DeLM §A.3) — is handled separately by the LLM verifier
in ``admission.py``. The old hard-coded placeholder-phrase blocklist was a brittle
deterministic proxy for that check and is now subsumed by it.
"""
from __future__ import annotations

from atria.core.blackboard.models import MAX_NOTE_CHARS, VALID_TYPES


def verify_notes(notes: list[dict]) -> tuple[list[dict], str]:
    """Type-normalize, cap to the note budget, and dedupe.

    Returns (clean_notes, status), where status is ``"ok:{kept}/{seen}"``.
    """
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []
    n_in = len(notes or [])
    for note in notes or []:
        t = str(note.get("type", "")).strip().upper()
        c = str(note.get("content", "")).strip()
        if t not in VALID_TYPES or not c:
            continue
        if len(c) > MAX_NOTE_CHARS:
            c = c[:MAX_NOTE_CHARS]
        key = (t, c)
        if key in seen:
            continue
        seen.add(key)
        clean.append({"type": t, "content": c})
    return clean, f"ok:{len(clean)}/{n_in}"
