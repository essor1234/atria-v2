"""Tests for domain_enrich tools registration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from atria.core.skill_tools import SkillToolContext, ToolSpec


class TestRegister:
    def test_returns_one_toolspec(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        specs = register(ctx)
        assert len(specs) == 1
        assert isinstance(specs[0], ToolSpec)

    def test_toolspec_named_domain_enrich(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert spec.name == "domain_enrich"

    def test_toolspec_requires_topic_parameter(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert "topic" in spec.parameters["properties"]
        assert "topic" in spec.parameters["required"]

    def test_toolspec_context_parameter_optional(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]
        assert "context" in spec.parameters["properties"]
        assert "context" not in spec.parameters.get("required", [])

    def test_handler_delegates_to_run_enrich(self):
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext(
            llm_chat=MagicMock(side_effect=['["q1","q2","q3"]', "synthesis"]),
            working_dir="/tmp",
        )
        spec = register(ctx)[0]

        with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=[]):
            result = spec.handler(topic="game events")

        assert "artifact_path" in result
        assert "summary" in result
        assert "sources" in result

    def test_handler_passes_context_to_run_enrich(self):
        from atria.skills.builtin.domain_enrich import engine
        from atria.skills.builtin.domain_enrich.tools import register

        ctx = SkillToolContext()
        spec = register(ctx)[0]

        with patch.object(engine, "run_enrich", return_value={}) as mock_run:
            spec.handler(topic="topic", context="some context")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["context"] == "some context"
