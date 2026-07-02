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
