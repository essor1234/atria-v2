"""Tests for the maintenance_copilot RoleClient (endpoint dispatch by role)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parent.parent / "modules" / "maintenance_copilot" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"mc_{name}_uut", _BASE / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"mc_{name}_uut"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeEmbeddings:
    def __init__(self):
        self.last_model: str = ""

    def create(self, model, input):
        # Echo one vector per input so we can assert dispatch + shape.
        self.last_model = model
        return type("R", (), {"data": [type("E", (), {"embedding": [0.1, 0.2]})()
                                        for _ in input]})()


class _FakeChat:
    class completions:
        @staticmethod
        def create(model, messages, **kw):
            return type("R", (), {"choices": [type("C", (), {
                "message": type("M", (), {"content": f"reply from {model}"})()})()]})()


class _FakeOpenAI:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.embeddings = _FakeEmbeddings()
        self.chat = _FakeChat()


def _make_counting_factory():
    """Return (factory, counter_list) where counter grows by 1 per call."""
    calls: list = []

    def factory(base_url: str, api_key: str) -> object:
        calls.append((base_url, api_key))
        return _FakeOpenAI(base_url, api_key)

    return factory, calls


def test_embed_returns_one_vector_per_text():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(
        config.load_config(env={"MC_INDEX_EMBED_MODEL": "embed-model-y"}),
        client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key),
    )
    vecs = rc.embed("index_embed", ["a", "b", "c"])
    assert len(vecs) == 3 and vecs[0] == [0.1, 0.2]
    # Verify the role's model was forwarded to the embeddings API.
    key = (rc._config["index_embed"].base_url, rc._config["index_embed"].api_key)
    fake_client = rc._clients[key]
    assert fake_client.embeddings.last_model == "embed-model-y"


def test_shared_endpoint_client_reused():
    """chunk_embed and index_embed share (base_url, api_key) by default.

    The factory must be called exactly once for that endpoint even when both
    roles are exercised.
    """
    config = _load("config")
    client_mod = _load("client")
    factory, calls = _make_counting_factory()
    rc = client_mod.RoleClient(config.load_config(env={}), client_factory=factory)
    rc.embed("index_embed", ["x"])
    rc.embed("chunk_embed", ["y"])
    # Both roles resolve to the same (base_url, api_key) → factory called once.
    assert len(calls) == 1


def test_chat_uses_the_roles_model():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(
        config.load_config(env={"MC_SYNTHESIS_MODEL": "role-model-x"}),
        client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key),
    )
    out = rc.chat("synthesis", [{"role": "user", "content": "hi"}])
    assert out == "reply from role-model-x"


def test_unknown_role_raises():
    config = _load("config")
    client_mod = _load("client")
    rc = client_mod.RoleClient(
        config.load_config(env={}),
        client_factory=lambda base_url, api_key: _FakeOpenAI(base_url, api_key),
    )
    with pytest.raises(ValueError):
        rc.embed("nope", ["x"])
