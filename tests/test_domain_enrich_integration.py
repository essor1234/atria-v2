"""Integration test: domain_enrich full pipeline with mocked search + LLM."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from atria.core.skill_tools import SkillToolContext
from atria.skills.builtin.domain_enrich.tools import register


def test_full_pipeline_produces_valid_artifact(tmp_path):
    """domain_enrich tool writes DOMAIN_SKILL.md with Summary and Raw Evidence."""
    chat_fn = MagicMock(
        side_effect=[
            '["game event taxonomy", "game analytics KPIs", "player behavior metrics"]',
            "Game events are discrete player actions (session starts, level completions, purchases) tracked as timestamped records for retention and monetization analysis.",
        ]
    )
    search_results = [
        {"title": "Game Analytics 101", "url": "https://gameanalytics.com/blog", "snippet": "Event tracking is the foundation of game analytics."},
        {"title": "KPI Guide", "url": "https://example.com/kpis", "snippet": "DAU, MAU, ARPU are core game metrics."},
    ]

    ctx = SkillToolContext(
        llm_chat=chat_fn,
        working_dir=str(tmp_path),
        on_artifact=None,
    )
    spec = register(ctx)[0]

    with patch("atria.skills.builtin.domain_enrich.engine.search_mod.search", return_value=search_results):
        result = spec.handler(topic="game event analytics", context="for mobile RPG")

    # Return value is well-formed
    assert result.get("artifact_path") is not None
    assert len(result.get("sources", [])) > 0
    assert len(result.get("summary", "")) > 0

    # Artifact file exists and has correct structure
    artifact = Path(result["artifact_path"])
    assert artifact.exists()
    assert artifact.name == "DOMAIN_SKILL.md"

    content = artifact.read_text()
    assert "# Domain Knowledge: game event analytics" in content
    assert "## Summary" in content
    assert "## Raw Evidence" in content
    assert "https://gameanalytics.com/blog" in content
    assert "Game Analytics 101" in content


def test_tool_registered_and_discoverable():
    """SkillToolLoader discovers domain_enrich via SKILL.md."""
    from pathlib import Path
    from atria.core.skill_tools import SkillToolContext, SkillToolLoader

    builtin_dir = Path(__file__).parent.parent / "atria" / "skills" / "builtin"
    loader = SkillToolLoader([builtin_dir])
    ctx = SkillToolContext()
    specs = loader.discover_and_register(ctx)

    names = [s.name for s in specs]
    assert "domain_enrich" in names, f"domain_enrich not found in: {names}"
