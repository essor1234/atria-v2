"""Apply the winning candidate's diff to the user's workspace with 3-way merge."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field


@dataclass
class ApplyResult:
    """Outcome of applying a diff: ok plus any files left with conflict markers."""

    ok: bool
    conflicted_files: list[str] = field(default_factory=list)


def apply_diff(repo_dir: str, diff: str) -> ApplyResult:
    """Apply ``diff`` onto repo_dir with ``git apply --3way``.

    On conflicts, markers are left in place (not reverted) and the conflicting files are
    reported. The caller retains the snapshot ref for recovery.
    """
    if not diff.strip():
        return ApplyResult(ok=False)
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as f:
        f.write(diff if diff.endswith("\n") else diff + "\n")
        patch_path = f.name
    p = subprocess.run(
        ["git", "apply", "--3way", patch_path],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode == 0:
        return ApplyResult(ok=True)
    # --3way leaves conflict markers and lists files in stderr ("U <file>" / "CONFLICT").
    conflicted: list[str] = []
    for line in (p.stderr or "").splitlines():
        s = line.strip()
        if s.startswith("U ") or "with conflicts" in s.lower():
            parts = s.split()
            if len(parts) >= 2:
                conflicted.append(parts[-1])
    return ApplyResult(ok=False, conflicted_files=conflicted)
