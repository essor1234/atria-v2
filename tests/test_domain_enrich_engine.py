"""Tests for domain_enrich engine."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from atria.skills.builtin.domain_enrich.engine import (
    _generate_queries,
    _synthesize,
    _write_artifact,
    run_enrich,
)


class TestGenerateQueries:
    def test_returns_three_queries_from_llm(self):
        chat_fn = MagicMock(return_value='["game events", "game analytics KPIs", "player retention"]')
        result = _generate_queries("game events", "", chat_fn)
        assert result == ["game events", "game analytics KPIs", "player retention"]

    def test_falls_back_to_defaults_on_invalid_json(self):
        chat_fn = MagicMock(return_value="I cannot generate queries")
        result = _generate_queries("game events", "", chat_fn)
        assert result == ["game events", "game events metrics", "game events best practices"]

    def test_includes_context_in_llm_prompt(self):
        chat_fn = MagicMock(return_value='["q1", "q2", "q3"]')
        _generate_queries("game events", "for mobile RPG", chat_fn)
        call_args = chat_fn.call_args
        user_prompt = call_args[0][1]
        assert "for mobile RPG" in user_prompt

    def test_falls_back_on_llm_exception(self):
        chat_fn = MagicMock(side_effect=Exception("LLM error"))
        result = _generate_queries("topic", "", chat_fn)
        assert len(result) == 3
        assert result[0] == "topic"


class TestSynthesize:
    def test_returns_llm_output(self):
        chat_fn = MagicMock(return_value="Game events are discrete player actions...")
        result = _synthesize("game events", ["evidence 1", "evidence 2"], chat_fn)
        assert result == "Game events are discrete player actions..."

    def test_handles_empty_evidence(self):
        chat_fn = MagicMock(return_value="Knowledge from training.")
        result = _synthesize("game events", [], chat_fn)
        assert "Knowledge from training." == result
        user_prompt = chat_fn.call_args[0][1]
        assert "No search results" in user_prompt

    def test_returns_error_string_on_llm_failure(self):
        chat_fn = MagicMock(side_effect=Exception("timeout"))
        result = _synthesize("topic", [], chat_fn)
        assert "unavailable" in result.lower()


class TestWriteArtifact:
    def test_creates_domain_skill_md(self, tmp_path):
        path = _write_artifact(
            topic="game events",
            context="for RPG",
            summary="Game events are actions...",
            results=[{"title": "Example", "url": "https://ex.com", "snippet": "A snippet"}],
            working_dir=str(tmp_path),
        )
        assert Path(path).exists()
        assert Path(path).name == "DOMAIN_SKILL.md"

    def test_artifact_contains_summary_and_evidence(self, tmp_path):
        path = _write_artifact(
            topic="game events",
            context="",
            summary="Summary text here",
            results=[{"title": "T", "url": "https://t.com", "snippet": "snippet text"}],
            working_dir=str(tmp_path),
        )
        content = Path(path).read_text()
        assert "## Summary" in content
        assert "Summary text here" in content
        assert "## Raw Evidence" in content
        assert "snippet text" in content
        assert "https://t.com" in content

    def test_writes_to_tempdir_when_working_dir_none(self):
        path = _write_artifact("topic", "", "summary", [], working_dir=None)
        assert Path(path).exists()
        Path(path).unlink(missing_ok=True)

    def test_overwrites_on_second_call(self, tmp_path):
        _write_artifact("t", "", "first", [], str(tmp_path))
        path = _write_artifact("t", "", "second", [], str(tmp_path))
        assert "second" in Path(path).read_text()
        assert "first" not in Path(path).read_text()


class TestRunEnrich:
    def test_returns_error_when_no_llm_chat(self, tmp_path):
        result = run_enrich("topic", "", chat_fn=None, working_dir=str(tmp_path), on_artifact=None)
        assert "error" in result
        assert result["artifact_path"] is None

    def test_full_pipeline_writes_artifact(self, tmp_path):
        chat_fn = MagicMock(
            side_effect=[
                '["game kpis", "game analytics", "game metrics"]',
                "Game events are discrete player actions tracked for analytics.",
            ]
        )
        search_results = [{"title": "T", "url": "https://t.com", "snippet": "snippet"}]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=search_results):
            result = run_enrich("game events", "for RPG", chat_fn, str(tmp_path), None)

        assert result["artifact_path"] is not None
        assert Path(result["artifact_path"]).exists()
        assert len(result["sources"]) > 0
        assert len(result["summary"]) > 0

    def test_deduplicates_search_results_by_url(self, tmp_path):
        chat_fn = MagicMock(
            side_effect=[
                '["q1", "q2", "q3"]',
                "synthesis",
            ]
        )
        duplicate_results = [{"title": "T", "url": "https://same.com", "snippet": "s"}]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=duplicate_results):
            result = run_enrich("topic", "", chat_fn, str(tmp_path), None)

        assert result["sources"].count("https://same.com") == 1

    def test_calls_on_artifact_callback(self, tmp_path):
        chat_fn = MagicMock(side_effect=['["q1", "q2", "q3"]', "synthesis"])
        on_artifact = MagicMock()

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            run_enrich("topic", "", chat_fn, str(tmp_path), on_artifact)

        on_artifact.assert_called_once()
        call_kwargs = on_artifact.call_args[0][0]
        assert call_kwargs["type"] == "domain_skill"
        assert "topic" in call_kwargs

    def test_proceeds_without_search_results(self, tmp_path):
        chat_fn = MagicMock(side_effect=['["q1", "q2", "q3"]', "Knowledge from training only."])

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            result = run_enrich("obscure topic", "", chat_fn, str(tmp_path), None)

        assert result["artifact_path"] is not None
        assert "Knowledge from training only." in result["summary"]
