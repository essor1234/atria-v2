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
