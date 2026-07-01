"""Build the cheap-model ``llm_call`` used by admission-time verification.

The DeLM paper (Fig 4c) shows a cheap model matches a frontier model for verification,
so we resolve a cheap slot rather than the main agent model:
``blackboard.verify_model`` -> ``model_critique`` -> ``model_compact`` -> ``model``.

Returns ``None`` (verification disabled / unavailable) when ``blackboard.verify`` is
off or no API key is configured. The OpenAI client is built once and reused across the
synchronous, thread-pooled verification calls.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def resolve_verify_model(config: Any) -> str:
    """Resolve the cheap model id used for admission verification."""
    bb_cfg = getattr(config, "blackboard", None)
    return (
        getattr(bb_cfg, "verify_model", None)
        or getattr(config, "model_critique", None)
        or getattr(config, "model_compact", None)
        or getattr(config, "model", None)
        or "gpt-4o-mini"
    )


def build_verify_llm(config: Any) -> Callable[[str, str], str] | None:
    """Return a synchronous ``(system, user) -> str`` verifier call, or None.

    None means "verification disabled or unavailable" — callers must treat this as
    "skip admission verification" so the blackboard still works without an API key.
    """
    bb_cfg = getattr(config, "blackboard", None)
    if bb_cfg is None or not getattr(bb_cfg, "verify", True):
        return None

    try:
        api_key = config.get_api_key()
    except Exception:  # noqa: BLE001
        api_key = None
    if not api_key:
        return None

    model = resolve_verify_model(config)
    base_url = getattr(config, "api_base_url", None) or "https://api.openai.com/v1"
    # AppConfig may store ".../chat/completions"; the OpenAI SDK appends it itself.
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]

    client_box: dict[str, Any] = {}

    def llm_chat(system: str, user: str) -> str:
        client = client_box.get("client")
        if client is None:
            from openai import OpenAI  # noqa: PLC0415

            client = OpenAI(api_key=api_key, base_url=base_url)
            client_box["client"] = client
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    return llm_chat
