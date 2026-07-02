"""Tests for the maintenance_copilot module-local model-provider config."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "modules" / "maintenance_copilot" / "scripts" / "config.py"
)


def _load_config_module():
    spec = importlib.util.spec_from_file_location("mc_config_under_test", _CONFIG_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mc_config_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_default_config_has_all_four_roles():
    mod = _load_config_module()
    cfg = mod.load_config(env={})
    assert set(cfg) == set(mod.ROLES)
    assert set(mod.ROLES) == {"chunk_embed", "index_embed", "synthesis", "kg_extract"}


def test_defaults_point_at_local_services():
    mod = _load_config_module()
    cfg = mod.load_config(env={})
    # Embeddings default to local TEI; synthesis defaults to local vLLM.
    assert "tei" in cfg["index_embed"].base_url or "8082" in cfg["index_embed"].base_url
    assert cfg["synthesis"].base_url.endswith("/v1")


def test_env_overrides_win_per_role():
    mod = _load_config_module()
    env = {
        "MC_SYNTHESIS_BASE_URL": "https://proxy.example/v1",
        "MC_SYNTHESIS_MODEL": "some-hosted-model",
    }
    cfg = mod.load_config(env=env)
    assert cfg["synthesis"].base_url == "https://proxy.example/v1"
    assert cfg["synthesis"].model == "some-hosted-model"
    # Untouched role keeps its default.
    assert cfg["index_embed"].base_url != "https://proxy.example/v1"
