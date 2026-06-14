"""LLM synthesis function tests."""

from unittest.mock import MagicMock

from atria.skills.builtin.deep_analyze.synthesis import (
    synthesize_executive_summary,
    synthesize_key_findings,
    synthesize_section,
)


_BRIEF = "test domain brief"


def _chat(response: str) -> MagicMock:
    m = MagicMock(return_value=response)
    return m


def test_synthesize_section_calls_chat_with_section_name() -> None:
    chat = _chat("Some narrative prose about compensation.")
    result = synthesize_section(
        section_name="Compensation Analysis",
        description="Examine salary distribution.",
        angles=["salary spread", "outlier roles"],
        stats_evidence="salary: mean=87000, outliers=3",
        chart_insights=["Bar chart shows Finance leads in salary."],
        chat_fn=chat,
        domain_brief=_BRIEF,
    )
    assert chat.called
    call_args = chat.call_args
    system_prompt, user_prompt = call_args[0]
    assert "Compensation Analysis" in user_prompt
    assert "salary spread" in user_prompt
    assert "salary: mean=87000" in user_prompt
    assert "Bar chart shows Finance" in user_prompt
    assert result == "Some narrative prose about compensation."


def test_synthesize_section_returns_fallback_on_error() -> None:
    def bad_chat(s, u):
        raise RuntimeError("API down")

    result = synthesize_section(
        section_name="Risk",
        description="Examine risk.",
        angles=[],
        stats_evidence="",
        chart_insights=[],
        chat_fn=bad_chat,
        domain_brief=_BRIEF,
    )
    assert "unavailable" in result


def test_synthesize_key_findings_calls_chat_with_section_contents() -> None:
    chat = _chat("- **Salary:** Finance pays 34% more.\n- **Risk:** 42% high risk.")
    sections = [
        {"name": "Compensation", "content": "Salary analysis here."},
        {"name": "Risk", "content": "Risk analysis here."},
    ]
    result = synthesize_key_findings(sections, chat, domain_brief=_BRIEF)
    assert chat.called
    _, user_prompt = chat.call_args[0]
    assert "Compensation" in user_prompt
    assert "Salary analysis here." in user_prompt
    assert "- **Salary:**" in result


def test_synthesize_executive_summary_includes_dataset_name() -> None:
    chat = _chat("This dataset covers 1,200 jobs across 10 industries.")
    sections = [{"name": "Compensation", "content": "Salary prose."}]
    result = synthesize_executive_summary(
        dataset_name="jobs_2030.csv",
        section_contents=sections,
        key_findings="- Salary premium exists.",
        chat_fn=chat,
        domain_brief=_BRIEF,
    )
    assert chat.called
    _, user_prompt = chat.call_args[0]
    assert "jobs_2030.csv" in user_prompt
    assert "Salary premium exists." in user_prompt
    assert "This dataset covers" in result


def test_synthesize_key_findings_skips_sections_without_content() -> None:
    chat = _chat("- **Finding:** something.")
    sections = [
        {"name": "Empty", "content": None},
        {"name": "Good", "content": "Some content."},
    ]
    synthesize_key_findings(sections, chat, domain_brief=_BRIEF)
    _, user_prompt = chat.call_args[0]
    assert "Good" in user_prompt
    assert "Empty" not in user_prompt


def test_synthesize_section_domain_brief_in_system_prompt() -> None:
    chat = _chat("narrative text")
    synthesize_section(
        section_name="Risk",
        description="Risk analysis.",
        angles=["risk premium"],
        stats_evidence="risk: mean=3.2",
        chart_insights=[],
        chat_fn=chat,
        domain_brief="workforce automation 2030",
    )
    system_arg = chat.call_args[0][0]
    assert "workforce automation 2030" in system_arg


def test_synthesize_exec_summary_domain_brief_in_system_prompt() -> None:
    chat = _chat("exec summary text")
    synthesize_executive_summary(
        dataset_name="jobs.csv",
        section_contents=[{"name": "Risk", "content": "Risk prose."}],
        key_findings="- Finding 1",
        chat_fn=chat,
        domain_brief="workforce automation 2030",
    )
    system_arg = chat.call_args[0][0]
    assert "workforce automation 2030" in system_arg
