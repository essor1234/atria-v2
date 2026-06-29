"""Snapshot the working tree (incl. uncommitted changes) as a base commit for worktrees."""
from __future__ import annotations

import subprocess


def _git(repo_dir: str, *args: str) -> tuple[int, str, str]:
    p = subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def snapshot_worktree(repo_dir: str) -> str:
    """Return a commit-ish capturing committed + uncommitted state.

    Uses ``git stash create`` when the tree is dirty (this writes a commit object WITHOUT
    touching the working tree or stash list), else HEAD. The returned ref is what solver
    worktrees fork from. It is a dangling commit; retain it for recovery until confirmed.
    """
    code, out, _ = _git(repo_dir, "stash", "create")
    if code == 0 and out:
        return out  # dirty: a new commit including tracked uncommitted changes
    code, head, _ = _git(repo_dir, "rev-parse", "HEAD")
    return head if code == 0 else "HEAD"


def discard_snapshot(repo_dir: str, ref: str) -> None:
    """Best-effort: drop a snapshot commit object (only call once recovery is no longer needed)."""
    # A `git stash create` commit is dangling; gc will reclaim it. Nothing to force-delete
    # safely without risking real refs, so this is intentionally a no-op placeholder that
    # documents intent. Retention-until-confirmed is the safety rail.
    return None
