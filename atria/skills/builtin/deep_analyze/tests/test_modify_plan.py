"""Tests for modify_plan()."""
import json
from atria.skills.builtin.deep_analyze.planning import modify_plan

_BASE_PLAN = {
    "summary": "Test dataset",
    "sections": [{"name": "Sec A", "description": "d", "chart_names": ["c1"], "analysis_angles": []}],
    "sub_tables": [{"name": "tbl1", "sql": "CREATE TABLE t_tbl1 AS SELECT * FROM raw", "why": "w"}],
    "charts": [{"name": "c1", "source_table": "t_tbl1", "type": "bar", "x": "col1", "y": ["col2"], "title": "T"}],
}


def test_modify_plan_returns_valid_plan():
    """modify_plan should return a dict with sections, sub_tables, charts."""
    def fake_chat(system: str, user: str) -> str:
        return json.dumps(_BASE_PLAN)

    result = modify_plan(_BASE_PLAN, "add a pie chart", fake_chat)
    assert "sections" in result
    assert "sub_tables" in result
    assert "charts" in result


def test_modify_plan_falls_back_on_parse_failure():
    """modify_plan should return original plan if LLM output is unparseable."""
    def bad_chat(system: str, user: str) -> str:
        return "not json at all"

    result = modify_plan(_BASE_PLAN, "do something", bad_chat)
    assert result == _BASE_PLAN
