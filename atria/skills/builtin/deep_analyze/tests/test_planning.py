"""Planning phase: schema profile -> structured plan JSON with sections."""

from unittest.mock import MagicMock

import pytest

from atria.skills.builtin.deep_analyze.planning import PlanningError, run_planning


_VALID_PLAN = """{
  "summary": "small sales sample",
  "sections": [
    {
      "name": "Revenue by Region",
      "description": "How revenue varies across geographic regions.",
      "chart_names": ["regional_revenue"],
      "analysis_angles": ["total revenue", "regional mix", "outliers"]
    }
  ],
  "sub_tables": [
    {"name": "by_region", "sql": "CREATE TABLE t_by_region AS SELECT region, SUM(revenue) r FROM raw GROUP BY region", "why": "regional mix"}
  ],
  "charts": [
    {"name": "regional_revenue", "source_table": "t_by_region", "type": "bar",
     "x": "region", "y": ["r"], "title": "Revenue by region"}
  ]
}"""

_BRIEF = "test domain brief"


def _fake_chat(responses: list[str]) -> MagicMock:
    m = MagicMock()
    m.side_effect = responses
    return m


def test_valid_plan_parses() -> None:
    plan = run_planning(
        {"file_name": "x.csv", "row_count": 3, "columns": []},
        chat=_fake_chat([_VALID_PLAN]),
        domain_brief=_BRIEF,
    )
    assert plan["sub_tables"][0]["name"] == "by_region"
    assert plan["charts"][0]["type"] == "bar"
    assert plan["sections"][0]["name"] == "Revenue by Region"
    assert plan["sections"][0]["chart_names"] == ["regional_revenue"]


def test_parse_failure_then_success_retries_once() -> None:
    chat = _fake_chat(["not json at all", _VALID_PLAN])
    plan = run_planning(
        {"file_name": "x.csv", "row_count": 3, "columns": []},
        chat=chat,
        domain_brief=_BRIEF,
    )
    assert chat.call_count == 2
    assert plan["summary"] == "small sales sample"


def test_two_consecutive_failures_raise() -> None:
    chat = _fake_chat(["nope", "still nope"])
    with pytest.raises(PlanningError):
        run_planning(
            {"file_name": "x.csv", "row_count": 3, "columns": []},
            chat=chat,
            domain_brief=_BRIEF,
        )


def test_empty_sub_tables_rejected() -> None:
    no_tables = """{
      "summary": "x",
      "sections": [{"name": "S", "description": "d", "chart_names": [], "analysis_angles": []}],
      "sub_tables": [],
      "charts": [{"name": "c", "source_table": "t_x", "type": "bar", "x": "a", "y": ["b"], "title": "T"}]
    }"""
    with pytest.raises(PlanningError, match="no work"):
        run_planning(
            {"file_name": "x.csv", "row_count": 3, "columns": []},
            chat=_fake_chat([no_tables]),
            domain_brief=_BRIEF,
        )


def test_missing_sections_rejected() -> None:
    no_sections = """{
      "summary": "x",
      "sub_tables": [{"name": "t", "sql": "CREATE TABLE t_t AS SELECT 1", "why": ""}],
      "charts": [{"name": "c", "source_table": "t_t", "type": "bar", "x": "a", "y": ["b"], "title": "T"}]
    }"""
    with pytest.raises(PlanningError, match="sections"):
        run_planning(
            {"file_name": "x.csv", "row_count": 3, "columns": []},
            chat=_fake_chat([no_sections]),
            domain_brief=_BRIEF,
        )


def test_empty_sections_list_rejected() -> None:
    empty_sections = """{
      "summary": "x",
      "sections": [],
      "sub_tables": [{"name": "t", "sql": "CREATE TABLE t_t AS SELECT 1", "why": ""}],
      "charts": [{"name": "c", "source_table": "t_t", "type": "bar", "x": "a", "y": ["b"], "title": "T"}]
    }"""
    with pytest.raises(PlanningError, match="no work"):
        run_planning(
            {"file_name": "x.csv", "row_count": 3, "columns": []},
            chat=_fake_chat([empty_sections]),
            domain_brief=_BRIEF,
        )


def test_domain_brief_injected_into_system_prompt() -> None:
    chat = _fake_chat([_VALID_PLAN])
    run_planning(
        {"file_name": "x.csv", "row_count": 3, "columns": []},
        chat=chat,
        domain_brief="workforce automation 2030",
    )
    system_arg = chat.call_args[0][0]
    assert "Domain Knowledge" in system_arg
    assert "workforce automation 2030" in system_arg


def test_empty_domain_brief_raises() -> None:
    """After EXPLORE, an empty brief surfaces a wiring bug instead of producing
    ungrounded analysis."""
    chat = _fake_chat([_VALID_PLAN])
    with pytest.raises(ValueError, match="domain_brief"):
        run_planning(
            {"file_name": "x.csv", "row_count": 3, "columns": []},
            chat=chat,
            domain_brief="",
        )
