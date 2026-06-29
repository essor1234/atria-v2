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
