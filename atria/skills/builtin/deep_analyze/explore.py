"""EXPLORE phase: clarification Q&A loop helpers.

The pipeline orchestrator drives the loop; this module provides the pure helpers
that build questions from the profile, assess confidence, and render the human-
readable bodies of the persisted clarification messages.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

ChatFn = Callable[[str, str], str]

CONFIDENCE_THRESHOLD = 0.75
MAX_ITERATIONS = 3

_INTENT_QUESTIONS: List[Dict[str, str]] = [
    {"id": "intent_decision", "text": "What decision or audience will this analysis inform?", "kind": "intent"},
    {"id": "intent_audience", "text": "Who is the intended audience for the report?", "kind": "intent"},
    {"id": "intent_focus", "text": "Are there specific patterns, metrics, or risks you want emphasised?", "kind": "intent"},
]


_AMBIGUITY_SYSTEM = """\
You are a data analyst preparing to study a new dataset. Examine the column profile
and propose targeted clarification questions ONLY for columns whose meaning, units,
encoding, or null-handling is ambiguous from the profile alone. Skip columns whose
purpose is obvious from the name.

Rules:
- Output 0–4 questions. If nothing is ambiguous, output an empty list.
- Each question: one short sentence, addressed to the dataset owner.
- Reference the column name explicitly in `column`.
- `kind` is always "ambiguity".

Return ONLY valid JSON in this shape:
{
  "questions": [
    {"id": "amb_<colname>", "text": "...", "kind": "ambiguity", "column": "<colname>"}
  ]
}
"""


_CONFIDENCE_SYSTEM = """\
You are a data analyst about to plan an analysis of a dataset. Given the profile,
the current domain brief, and any Q&A so far, judge how confident you are that you
understand the dataset well enough to write a meaningful analysis plan.

Output ONLY valid JSON:
{"confidence": <float between 0.0 and 1.0>, "reason": "one short sentence"}
"""


def _profile_digest(profile: Dict[str, Any]) -> str:
    """Compact profile summary used as user-prompt input."""
    cols = profile.get("columns", [])
    lines = [f"Row count: {profile.get('row_count', '?')}", "Columns:"]
    for col in cols:
        dtype = col.get("dtype", "?")
        null_pct = col.get("null_pct", 0)
        bits = [f"type={dtype}", f"nulls={null_pct:.1%}"]
        if dtype in {"int", "float"}:
            if col.get("mean") is not None:
                bits.append(f"mean={col['mean']:.2f}")
            if col.get("outlier_count"):
                bits.append(f"outliers={col['outlier_count']}")
        else:
            tvs = col.get("top_values", [])[:3]
            if tvs:
                bits.append("top=" + ",".join(str(v["value"]) for v in tvs))
        lines.append(f"  - {col['name']} ({', '.join(bits)})")
    return "\n".join(lines)


def _parse_json(raw: str) -> Dict[str, Any]:
    """Strip code fences if present and json.loads the body."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


def generate_intent_questions() -> List[Dict[str, str]]:
    """Return the fixed intent question bundle for iteration 1."""
    return [dict(q) for q in _INTENT_QUESTIONS]


def generate_ambiguity_questions(
    profile: Dict[str, Any],
    domain_brief: str,
    prior_qa: List[Dict[str, Any]],
    chat_fn: ChatFn,
) -> List[Dict[str, Any]]:
    """Ask the LLM for ambiguity questions targeting cryptic columns / null patterns."""
    asked_columns = {qa.get("column") for qa in prior_qa if qa.get("column")}
    user = (
        f"Profile digest:\n{_profile_digest(profile)}\n\n"
        f"Current domain brief:\n{domain_brief or '(empty)'}\n\n"
        f"Already-asked columns (do not re-ask): {sorted(c for c in asked_columns if c)}\n\n"
        "Propose ambiguity questions."
    )
    try:
        raw = chat_fn(_AMBIGUITY_SYSTEM, user)
        payload = _parse_json(raw)
        questions = payload.get("questions", [])
        if not isinstance(questions, list):
            return []
        out: List[Dict[str, Any]] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            if not q.get("text"):
                continue
            q.setdefault("kind", "ambiguity")
            q.setdefault("id", f"amb_{q.get('column', len(out))}")
            out.append(q)
        return out
    except Exception as e:
        logger.warning("generate_ambiguity_questions failed: %s", e)
        return []


def assess_confidence(
    profile: Dict[str, Any],
    domain_brief: str,
    qa_transcript: List[Dict[str, Any]],
    chat_fn: ChatFn,
) -> float:
    """Return the LLM's self-assessed confidence (0.0–1.0). On error, returns 1.0
    so the loop exits rather than spinning forever on a broken LLM call."""
    qa_block = "\n".join(
        f"Q: {qa.get('text', '')}\nA: {qa.get('answer', '')}" for qa in qa_transcript
    ) or "(none yet)"
    user = (
        f"Profile digest:\n{_profile_digest(profile)}\n\n"
        f"Domain brief:\n{domain_brief or '(empty)'}\n\n"
        f"Q&A so far:\n{qa_block}\n\n"
        "Assess your confidence."
    )
    try:
        raw = chat_fn(_CONFIDENCE_SYSTEM, user)
        payload = _parse_json(raw)
        score = float(payload.get("confidence", 0.0))
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning("assess_confidence failed (treating as confident to exit loop): %s", e)
        return 1.0


def render_questions_md(questions: List[Dict[str, Any]]) -> str:
    """Render a question batch as a human-readable markdown body for chat persistence."""
    if not questions:
        return "_No clarifying questions — proceeding with analysis._"
    lines = ["**A few questions before I analyse this dataset:**", ""]
    for i, q in enumerate(questions, 1):
        col_suffix = f" (column: `{q['column']}`)" if q.get("column") else ""
        lines.append(f"{i}. {q['text']}{col_suffix}")
    return "\n".join(lines)


def render_answers_md(questions: List[Dict[str, Any]], answers: List[Dict[str, Any]]) -> str:
    """Render the user's answers as a markdown body, pairing each Q with its answer."""
    q_by_id = {q["id"]: q for q in questions}
    lines: List[str] = []
    for a in answers:
        qid = a.get("id")
        q = q_by_id.get(qid)
        if q is None:
            continue
        lines.append(f"**Q:** {q['text']}")
        lines.append(f"**A:** {a.get('answer', '').strip() or '_(skipped)_'}")
        lines.append("")
    return "\n".join(lines).rstrip() or "_(no answers provided)_"


def merge_qa(
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    iteration: int,
) -> List[Dict[str, Any]]:
    """Pair questions with their answers into transcript records.

    Output records are stable dicts with keys: id, text, kind, column (optional),
    answer, iteration. Used for prompt injection and message metadata.
    """
    ans_by_id = {a.get("id"): (a.get("answer") or "").strip() for a in answers}
    records: List[Dict[str, Any]] = []
    for q in questions:
        rec = {
            "id": q["id"],
            "text": q["text"],
            "kind": q.get("kind", "ambiguity"),
            "answer": ans_by_id.get(q["id"], ""),
            "iteration": iteration,
        }
        if q.get("column"):
            rec["column"] = q["column"]
        records.append(rec)
    return records
