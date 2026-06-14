"""Planning LLM call: dataset profile -> sections + sub_tables + charts plan."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Optional

from .prompts import build_planning_system

logger = logging.getLogger(__name__)


class PlanningError(RuntimeError):
    pass


def _strip_fences(raw: str) -> str:
    if "```" not in raw:
        return raw.strip()
    for fence in ("```json", "```"):
        if fence in raw:
            return raw.split(fence, 1)[-1].split("```")[0].strip()
    return raw.strip()


def _strip_t_prefix(name: str) -> str:
    return name[2:] if isinstance(name, str) and name.startswith("t_") else name


def _parse_plan(raw: str) -> Dict[str, Any]:
    plan = json.loads(_strip_fences(raw))
    for key in ("sub_tables", "charts", "sections"):
        if key not in plan or not isinstance(plan[key], list):
            raise ValueError(f"plan missing list `{key}`")
    for spec in plan["sub_tables"]:
        if isinstance(spec, dict) and "name" in spec:
            spec["name"] = _strip_t_prefix(spec["name"])
    for chart in plan["charts"]:
        if isinstance(chart, dict) and "source_table" in chart:
            st = chart["source_table"]
            if isinstance(st, str) and st.startswith("t_t_"):
                chart["source_table"] = st[2:]
    return plan


def _sanitize(obj: Any) -> Any:
    """Recursively convert numpy scalars to native Python types for JSON safety."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    # numpy scalars expose __bool__/__float__/__int__ but aren't json-native
    t = type(obj).__name__
    if t.startswith("bool"):
        return bool(obj)
    if t.startswith("int") or t.startswith("uint"):
        return int(obj)
    if t.startswith("float"):
        return float(obj)
    return obj


def run_planning(
    profile: Dict[str, Any],
    chat: Callable[[str, str], str],
    domain_brief: str = "",
    depth: str = "standard",
) -> Dict[str, Any]:
    system = build_planning_system(domain_brief, depth)
    user = json.dumps(_sanitize(profile), ensure_ascii=False)
    import concurrent.futures  # noqa: PLC0415

    last_err: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(chat, system, user)
                try:
                    raw = future.result(timeout=300)
                except concurrent.futures.TimeoutError:
                    raise PlanningError("planning LLM call timed out after 300s")
            plan = _parse_plan(raw)
            if not plan["sub_tables"] or not plan["charts"] or not plan["sections"]:
                raise PlanningError("planner produced no work")
            return plan
        except PlanningError:
            raise
        except Exception as e:
            if last_err is None:
                last_err = e
            logger.warning("planning parse failure (attempt %s): %s", attempt, e)
    raise PlanningError(f"planning failed after 2 attempts: {last_err}")


_MODIFY_SYSTEM = (
    "You are a data-analysis planner. The user has an existing analysis plan and wants "
    "to modify it. Apply their instructions and return ONLY the updated plan as valid JSON "
    "with the same structure: {summary, sections, sub_tables, charts}. "
    "Follow the same rules as before: sub_tables must SELECT only from `raw`, "
    "chart types must be bar/line/scatter/hist/pie, all referenced columns must exist. "
    "Return ONLY valid JSON — no prose, no markdown fences."
)


def modify_plan(
    plan: Dict[str, Any],
    instructions: str,
    chat: Callable[[str, str], str],
    timeout: int = 90,
) -> Dict[str, Any]:
    """Apply user modification instructions to an existing plan via LLM.

    Falls back to the original plan on parse failure or timeout.
    """
    import concurrent.futures  # noqa: PLC0415

    user = (
        f"Current plan:\n{json.dumps(_sanitize(plan), ensure_ascii=False)}\n\n"
        f"Modification request: {instructions}"
    )
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(chat, _MODIFY_SYSTEM, user)
            try:
                raw = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.warning("modify_plan timed out after %ds — keeping original plan", timeout)
                return plan
        return _parse_plan(raw)
    except Exception as e:
        logger.warning("modify_plan failed (%s) — keeping original plan", e)
        return plan
