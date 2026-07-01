"""Admission-time LLM verification for the shared blackboard (DeLM §A.3).

The DeLM paper's largest single accuracy contributor (Fig 4a: removing it drops
60.1 -> 55.2%) is that only *verified* updates enter the shared context: a note is
checked against its supporting evidence before it becomes durable state other agents
build on. Unsupported or speculative claims are rejected rather than silently admitted.

This module implements the paper's cheap "reasoning-trajectory" path: a single yes/no
LLM call per note asking whether the note states a specific, grounded, already-established
finding (vs. speculation, intent, or specifics not backed by its own stated evidence).
Per Fig 4c a cheap model matches a frontier model here, so this runs on a cheap slot.

Design notes:
- **Fail-open.** The blackboard is an accelerant that must never break a run, so any
  verifier error or unparseable response admits the note (we never lose real work to a
  flaky verifier). The deterministic hygiene gate in ``verifier.py`` still always runs.
- **Concurrent.** Notes are verified in parallel (paper §A.4), bounded by a semaphore,
  via ``run_in_executor`` so the synchronous ``llm_call`` does not block the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are an admission verifier for a shared multi-agent knowledge board. Each "
    "admitted note becomes durable state other agents trust and build on, so a "
    "speculative note can mislead the whole team.\n"
    "ADMIT a note that records a concrete, already-established finding, failure, "
    "observation, or constraint. Specific file paths, line numbers, and described "
    "behaviors are exactly what belongs on the board — do NOT reject a note merely for "
    "being specific; concrete specifics are the point.\n"
    "REJECT only when the note is: speculation or a prediction ('will probably', 'should "
    "fix', 'might'); an intention or plan rather than a result; hedged or uncertain; vague "
    "with no concrete content; or internally contradictory. For a PATCH_SUMMARY, also "
    "reject if its 'evidence=' field is empty, a placeholder, or does not actually support "
    "its 'idea='.\n"
    'Reply with STRICT JSON only: {"ok": true|false, "reason": "<=12 words"}.'
)


def _user_prompt(note: dict) -> str:
    return (
        f"Note type: {note.get('type', '')}\n"
        f"Note content: {note.get('content', '')}\n\n"
        "Should this note be admitted to the shared context?"
    )


def _parse(raw: str) -> tuple[bool, str]:
    """Parse the verifier's JSON verdict. Unparseable -> fail-open admit."""
    try:
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        obj = json.loads(match.group(0)) if match else {}
        return bool(obj.get("ok", True)), str(obj.get("reason", ""))[:120]
    except Exception:  # noqa: BLE001 — fail-open on any parse glitch
        return True, ""


async def admit_notes(
    notes: list[dict],
    llm_call: Callable[[str, str], str],
    *,
    concurrency_limit: int = 8,
) -> tuple[list[dict], list[str]]:
    """Verify clean notes concurrently; return ``(admitted, rejection_reasons)``.

    Args:
        notes: Already-hygiene-checked notes (``{"type", "content"}``).
        llm_call: Synchronous ``(system, user) -> str`` verifier model call.
        concurrency_limit: Max in-flight verification calls.

    Fail-open: a note whose verification errors or returns unparseable output is admitted.
    """
    if not notes:
        return [], []
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(max(1, concurrency_limit))

    async def _check(note: dict) -> tuple[dict, bool, str]:
        async with sem:
            try:
                raw = await loop.run_in_executor(
                    None, llm_call, _SYSTEM, _user_prompt(note)
                )
            except Exception as exc:  # noqa: BLE001 — fail-open, never break the run
                logger.warning("blackboard admission verify errored (admitting): %s", exc)
                return note, True, ""
            ok, reason = _parse(raw)
            return note, ok, reason

    results = await asyncio.gather(*[_check(n) for n in notes])

    admitted: list[dict] = []
    reasons: list[str] = []
    for note, ok, reason in results:
        if ok:
            admitted.append(note)
        else:
            reasons.append(f"{note.get('type', '')}: {reason}".strip())
    return admitted, reasons
