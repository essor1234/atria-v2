"""Turn a user request into a validated task DAG via one LLM call.

No raising into callers above DecomposeError.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from atria.core.divide.models import DivideTask

_SYSTEM = (
    "You split a user's request about ONE module into a small DAG of subtasks for "
    "parallel worker agents. Output ONLY a JSON array, no prose. Each element: "
    '{"id": "t1", "description": "<one concrete subtask>", "depends_on": ["<ids>"]}. '
    "Keep tasks independent where possible; use depends_on only for true ordering. "
    "Use the module's documented commands. Max tasks as instructed."
)


class DecomposeError(Exception):
    """Raised when the LLM output cannot be turned into a valid task DAG."""


def _extract_json_array(text: str) -> list:
    """Extract JSON array from text, tolerating code fences.

    Args:
        text: Text containing or wrapping a JSON array.

    Returns:
        Parsed JSON array.

    Raises:
        ValueError: If no JSON array is found.
    """
    text = text.strip()
    # Tolerate code fences around the array.
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON array found")
    return json.loads(m.group(0))


def _validate(raw: list, max_tasks: int) -> list[DivideTask]:
    """Validate a raw task list and convert to DivideTask objects.

    Checks:
    - Non-empty list
    - Count <= max_tasks
    - No duplicate IDs
    - All dependencies reference existing task IDs
    - No cycles in the dependency graph

    Args:
        raw: Parsed JSON array of task dicts.
        max_tasks: Maximum allowed number of tasks.

    Returns:
        List of validated DivideTask objects.

    Raises:
        DecomposeError: If validation fails.
    """
    if not isinstance(raw, list) or not raw:
        raise DecomposeError("empty or non-list DAG")
    if len(raw) > max_tasks:
        raise DecomposeError(f"too many tasks: {len(raw)} > {max_tasks}")
    tasks = [
        DivideTask(
            id=str(d["id"]),
            description=str(d["description"]),
            depends_on=[str(x) for x in d.get("depends_on", [])],
        )
        for d in raw
    ]
    ids = [t.id for t in tasks]
    if len(set(ids)) != len(ids):
        raise DecomposeError("duplicate task ids")
    idset = set(ids)
    for t in tasks:
        for dep in t.depends_on:
            if dep not in idset:
                raise DecomposeError(f"task {t.id} depends on unknown {dep}")
    # Cycle check via DFS.
    graph = {t.id: t.depends_on for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}

    def visit(node: str) -> None:
        color[node] = GRAY
        for dep in graph[node]:
            if color[dep] == GRAY:
                raise DecomposeError("dependency cycle detected")
            if color[dep] == WHITE:
                visit(dep)
        color[node] = BLACK

    for i in ids:
        if color[i] == WHITE:
            visit(i)
    return tasks


def decompose(
    request: str,
    module_skill: str,
    llm_call: Callable[[str, str], str],
    max_tasks: int,
) -> list[DivideTask]:
    """Ask the LLM for a task DAG; validate it. Retry once on parse failure.

    Args:
        request: User's request to decompose.
        module_skill: Module skill documentation/description.
        llm_call: Function taking (system_prompt, user_prompt) -> assistant_text.
        max_tasks: Maximum allowed tasks in the DAG.

    Returns:
        Validated list of DivideTask objects forming a DAG.

    Raises:
        DecomposeError: If LLM output is invalid or unparseable after one retry.
    """
    user = (
        f"Module skill:\n{module_skill}\n\nUser request:\n{request}\n\n"
        f"Max tasks: {max_tasks}"
    )
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            raw = _extract_json_array(llm_call(_SYSTEM, user))
            return _validate(raw, max_tasks)
        except DecomposeError:
            raise
        except Exception as exc:  # noqa: BLE001 — parse/format errors retry once
            last_exc = exc
    raise DecomposeError(f"could not parse DAG: {last_exc}")
