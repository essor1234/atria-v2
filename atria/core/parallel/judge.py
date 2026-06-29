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
