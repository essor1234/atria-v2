"""Tests for deep_analyze.explore."""

from __future__ import annotations

import json

import pytest

from atria.skills.builtin.deep_analyze import explore


def _profile() -> dict:
    return {
        "row_count": 1000,
        "columns": [
            {"name": "acct_cd", "dtype": "string", "null_pct": 0.0, "top_values": [{"value": "A", "count": 400}]},
            {"name": "salary", "dtype": "float", "null_pct": 0.01, "mean": 50000.0, "outlier_count": 4},
        ],
    }


def test_generate_intent_questions_returns_fixed_three():
    qs = explore.generate_intent_questions()
    assert len(qs) == 3
    assert all(q["kind"] == "intent" for q in qs)
    assert {q["id"] for q in qs} == {"intent_decision", "intent_audience", "intent_focus"}


def test_generate_ambiguity_questions_parses_llm_response():
    fake_response = json.dumps({
        "questions": [
            {"id": "amb_acct_cd", "text": "What does acct_cd encode?", "column": "acct_cd"},
        ]
    })
    chat = lambda s, u: fake_response
    qs = explore.generate_ambiguity_questions(_profile(), "", [], chat)
    assert len(qs) == 1
    assert qs[0]["column"] == "acct_cd"
    assert qs[0]["kind"] == "ambiguity"


def test_generate_ambiguity_questions_strips_code_fences():
    fake = "```json\n" + json.dumps({"questions": [{"id": "x", "text": "Q?", "column": "c"}]}) + "\n```"
    qs = explore.generate_ambiguity_questions(_profile(), "", [], lambda s, u: fake)
    assert len(qs) == 1


def test_generate_ambiguity_questions_handles_llm_failure():
    chat = lambda s, u: "not valid json"
    qs = explore.generate_ambiguity_questions(_profile(), "", [], chat)
    assert qs == []


def test_generate_ambiguity_questions_skips_invalid_entries():
    fake = json.dumps({"questions": [{"id": "x"}, {"text": "Q1", "column": "c"}]})
    qs = explore.generate_ambiguity_questions(_profile(), "", [], lambda s, u: fake)
    assert len(qs) == 1
    assert qs[0]["text"] == "Q1"


def test_assess_confidence_parses_score():
    fake = json.dumps({"confidence": 0.82, "reason": "clear"})
    score = explore.assess_confidence(_profile(), "brief", [], lambda s, u: fake)
    assert score == pytest.approx(0.82)


def test_assess_confidence_clamps_out_of_range_values():
    fake = json.dumps({"confidence": 1.7})
    assert explore.assess_confidence(_profile(), "", [], lambda s, u: fake) == 1.0
    fake_neg = json.dumps({"confidence": -0.2})
    assert explore.assess_confidence(_profile(), "", [], lambda s, u: fake_neg) == 0.0


def test_assess_confidence_returns_one_on_llm_failure():
    assert explore.assess_confidence(_profile(), "", [], lambda s, u: "garbage") == 1.0


def test_render_questions_md_lists_each_question():
    qs = [
        {"id": "q1", "text": "What is X?", "kind": "intent"},
        {"id": "q2", "text": "What is Y?", "kind": "ambiguity", "column": "y"},
    ]
    md = explore.render_questions_md(qs)
    assert "1. What is X?" in md
    assert "2. What is Y? (column: `y`)" in md


def test_render_questions_md_handles_empty():
    md = explore.render_questions_md([])
    assert "No clarifying questions" in md


def test_render_answers_md_pairs_questions_with_answers():
    qs = [{"id": "q1", "text": "What is X?"}]
    ans = [{"id": "q1", "answer": "It is foo"}]
    md = explore.render_answers_md(qs, ans)
    assert "What is X?" in md and "It is foo" in md


def test_merge_qa_includes_iteration_and_column():
    qs = [{"id": "q1", "text": "Q?", "kind": "ambiguity", "column": "acct_cd"}]
    ans = [{"id": "q1", "answer": "An account code"}]
    records = explore.merge_qa(qs, ans, iteration=2)
    assert records == [{
        "id": "q1",
        "text": "Q?",
        "kind": "ambiguity",
        "answer": "An account code",
        "iteration": 2,
        "column": "acct_cd",
    }]


def test_merge_qa_treats_missing_answer_as_empty_string():
    qs = [{"id": "q1", "text": "Q?"}]
    records = explore.merge_qa(qs, [], iteration=1)
    assert records[0]["answer"] == ""


def test_constants_match_spec():
    assert explore.CONFIDENCE_THRESHOLD == 0.75
    assert explore.MAX_ITERATIONS == 3
