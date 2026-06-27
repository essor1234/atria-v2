"""Tests for per-run BlackboardHandle provisioning (flag-gated, accelerant)."""
from __future__ import annotations

from types import SimpleNamespace

import fakeredis.aioredis

from atria.core.blackboard.provision import (
    make_run_blackboard,
    teardown_run_blackboard,
)


def _cfg(enabled: bool) -> SimpleNamespace:
    """Build a tiny stub AppConfig with a .blackboard section."""
    return SimpleNamespace(
        blackboard=SimpleNamespace(
            enabled=enabled,
            redis_url="redis://localhost:6379/0",
            ttl=3600,
            window_tokens=2000,
        )
    )


def test_disabled_returns_none() -> None:
    """make_run_blackboard returns None when the flag is off."""
    handle = make_run_blackboard(
        config=_cfg(enabled=False),
        task_id="t1",
        owner_id="o1",
    )
    assert handle is None


def test_missing_blackboard_config_returns_none() -> None:
    """A config without a blackboard section yields None (no crash)."""
    handle = make_run_blackboard(config=SimpleNamespace(), task_id="t1", owner_id="o1")
    assert handle is None


def test_enabled_with_injected_client_starts_handle() -> None:
    """With enabled=True and an injected client, a started handle is returned.

    The injected client is caller-owned, so teardown must be clean and must
    NOT close the caller's client (we never assert it is closed).
    """
    client = fakeredis.aioredis.FakeRedis()
    handle = make_run_blackboard(
        config=_cfg(enabled=True),
        task_id="task-prov",
        owner_id="owner-prov",
        redis_client=client,
    )
    assert handle is not None
    try:
        status = handle.write([{"type": "FACT", "content": "the sky is blue"}])
        assert status == "ok:1/1"
        digest = handle.render()
        assert "the sky is blue" in digest
    finally:
        teardown_run_blackboard(handle)


def test_teardown_none_is_noop() -> None:
    """teardown_run_blackboard(None) does nothing and does not raise."""
    teardown_run_blackboard(None)
