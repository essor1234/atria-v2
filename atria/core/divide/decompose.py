"""Turn a user request into a validated task DAG via one LLM call.

No raising into callers above DecomposeError.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from atria.core.divide.models import DivideTask

logger = logging.getLogger(__name__)

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


_REDECOMPOSE_SYSTEM = (
    "You are reviewing progress on a user's request that was split into subtasks for "
    "parallel worker agents. The task queue is now empty. Using the original request, "
    "the completed subtasks, and the shared verified context, decide whether the request "
    "is fully addressed. If it is COMPLETE, output exactly: DONE. If MORE work is clearly "
    "needed, output ONLY a JSON array of NEW subtasks, each "
    '{"id": "<new unique id>", "description": "<one concrete subtask>", '
    '"depends_on": ["<existing or new ids>"]}. New ids must NOT reuse existing ids; '
    "depends_on may reference existing (completed) ids. Be conservative — add a task only "
    "when it is necessary to satisfy the original request; never add busywork."
)


def _extract_json_tasks(text: str) -> list | None:
    """Parse a re-decomposition reply into a list of task dicts, or None.

    Tolerates a top-level JSON array ``[{...}]`` or a single bare object ``{...}`` (models
    often emit one task unwrapped), and trailing prose. Uses a balanced-delimiter scan from
    the first ``[``/``{`` so an inner array (e.g. ``depends_on``) is never mistaken for the
    top-level structure. Returns None when nothing parseable is found.
    """
    text = (text or "").strip()
    start = next((i for i, ch in enumerate(text) if ch in "[{"), None)
    if start is None:
        return None
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    escaped = False
    end = None
    for j in range(start, len(text)):
        ch = text[j]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = j
                break
    if end is None:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:  # noqa: BLE001
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    return None


def _validate_new(raw: list, existing_ids: set[str], max_tasks: int) -> list[DivideTask]:
    """Validate a re-decomposition batch. Returns [] on any problem (fail-safe).

    New ids must be unique and disjoint from ``existing_ids``; dependencies may point to
    existing ids or other new ids; the new sub-DAG must be acyclic. Unlike :func:`_validate`
    this never raises — re-decomposition is best-effort and must not fail a running job.
    """
    if not isinstance(raw, list) or not raw or len(raw) > max_tasks:
        return []
    try:
        tasks = [
            DivideTask(
                id=str(d["id"]),
                description=str(d["description"]),
                depends_on=[str(x) for x in d.get("depends_on", [])],
            )
            for d in raw
        ]
    except Exception:  # noqa: BLE001 — malformed batch -> treat as DONE
        return []
    new_ids = [t.id for t in tasks]
    if len(set(new_ids)) != len(new_ids):
        return []
    if existing_ids & set(new_ids):
        return []
    known = existing_ids | set(new_ids)
    for t in tasks:
        if any(dep not in known for dep in t.depends_on):
            return []
    # Cycle check over new tasks only (existing tasks are complete and cannot close a cycle).
    graph = {t.id: [d for d in t.depends_on if d in set(new_ids)] for t in tasks}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in new_ids}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for dep in graph[node]:
            if color[dep] == GRAY:
                return False
            if color[dep] == WHITE and not visit(dep):
                return False
        color[node] = BLACK
        return True

    for i in new_ids:
        if color[i] == WHITE and not visit(i):
            return []
    return tasks


def redecompose(
    request: str,
    module_skill: str,
    completed: str,
    digest: str,
    existing_ids: set[str],
    llm_call: Callable[[str, str], str],
    max_tasks: int,
) -> list[DivideTask]:
    """Decide whether more subtasks are needed (DeLM stage 4). Never raises.

    Returns new validated tasks, or ``[]`` when the request is complete / the model
    declines / output is unparseable (all treated as "done, no more work").
    """
    user = (
        f"Module skill:\n{module_skill}\n\nOriginal request:\n{request}\n\n"
        f"Subtask progress:\n{completed}\n\n"
        f"Shared verified context:\n{digest or '(empty)'}\n\n"
        f"Existing task ids: {sorted(existing_ids)}\n\nMax NEW tasks: {max_tasks}"
    )
    try:
        text = (llm_call(_REDECOMPOSE_SYSTEM, user) or "").strip()
    except Exception as exc:  # noqa: BLE001 — best-effort follow-up
        logger.warning("redecompose llm_call failed: %s", exc)
        return []
    if not text or text.upper().startswith("DONE"):
        return []
    raw = _extract_json_tasks(text)
    if raw is None:
        return []
    return _validate_new(raw, existing_ids, max_tasks)


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
