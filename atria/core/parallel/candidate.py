"""Extract one solver's candidate solution: its worktree diff + verified PATCH_SUMMARY."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class Candidate:
    """A solver's candidate: the diff its worktree produced + its PATCH_SUMMARY note."""

    thread_id: int
    diff: str
    patch_summary: str
    ok: bool


def _git_diff(worktree_path: str, base_ref: str) -> str:
    try:
        p = subprocess.run(
            ["git", "diff", base_ref],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # Missing/removed worktree or git failure → no diff (candidate is unusable).
        return ""
    return p.stdout if p.returncode == 0 else ""


def extract_candidate(worktree_path: str, base_ref: str, notes: list, thread_id: int) -> Candidate:
    """Build a Candidate from a solver's worktree diff and its latest PATCH_SUMMARY note.

    Args:
        worktree_path: The solver's worktree directory.
        base_ref: The snapshot commit the worktrees forked from.
        notes: All blackboard notes (each has .type/.content/.thread_id or dict keys).
        thread_id: Which solver this candidate is for.
    """
    diff = _git_diff(worktree_path, base_ref)

    def _f(n, k):
        return getattr(n, k, None) if not isinstance(n, dict) else n.get(k)

    summaries = [
        _f(n, "content")
        for n in notes
        if _f(n, "type") == "PATCH_SUMMARY" and int(_f(n, "thread_id") or 0) == thread_id
    ]
    patch_summary = summaries[-1] if summaries else ""
    ok = bool(diff.strip()) and bool(patch_summary)
    return Candidate(thread_id=thread_id, diff=diff, patch_summary=patch_summary, ok=ok)
