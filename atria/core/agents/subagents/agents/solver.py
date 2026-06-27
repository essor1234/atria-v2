"""Solver subagent: one autonomous parallel solver (DeLM Phase 2b)."""

from atria.core.agents.prompts.loader import load_prompt
from atria.core.agents.subagents.specs import SubAgentSpec

SOLVER_SUBAGENT = SubAgentSpec(
    name="solver",
    description=(
        "Autonomous parallel solver. Attempts one task in an isolated git worktree, "
        "shares verified notes with peer solvers via the blackboard, and emits a "
        "PATCH_SUMMARY for the judge. USE FOR: the per-solver runs spawned by "
        "solve_parallel (not invoked directly)."
    ),
    system_prompt=load_prompt("subagents/subagent-solver"),
    tools=[
        "read_file",
        "search",
        "list_files",
        "find_symbol",
        "find_referencing_symbols",
        "edit_file",
        "write_file",
        "run_command",
        "NOTE",
    ],
)
