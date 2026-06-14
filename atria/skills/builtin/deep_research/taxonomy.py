"""Taxonomy generation and modification via LLM."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from typing import Callable

from .prompts import MODIFY_TAXONOMY_SYSTEM, TAXONOMY_SYSTEM

ChatFn = Callable[[str, str], str]


def _client():
    from openai import OpenAI  # noqa: PLC0415

    return OpenAI(
        api_key=os.environ.get("DEEP_RESEARCH_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("DEEP_RESEARCH_BASE_URL", "https://api.openai.com/v1"),
    )


def _extra_body() -> Optional[Dict[str, Any]]:
    raw = os.environ.get("DEEP_RESEARCH_EXTRA_BODY", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def chat(system: str, user: str) -> str:
    response = _client().chat.completions.create(
        model=os.environ.get("DEEP_RESEARCH_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        extra_body=_extra_body(),
    )
    return (response.choices[0].message.content or "").strip()


def _strip_fences(raw: str) -> str:
    if "```" not in raw:
        return raw
    for fence in ("```json", "```"):
        if fence in raw:
            return raw.split(fence, 1)[-1].split("```")[0].strip()
    return raw


def generate_taxonomy(topic: str, chat_fn: ChatFn | None = None) -> Dict[str, Any]:
    fn = chat_fn or chat
    raw = fn(TAXONOMY_SYSTEM, f"Topic: {topic}")
    return json.loads(_strip_fences(raw))


def modify_taxonomy(
    taxonomy: Dict[str, Any],
    instructions: str,
    chat_fn: ChatFn | None = None,
) -> Dict[str, Any]:
    user_prompt = (
        f"Current taxonomy:\n{json.dumps(taxonomy, ensure_ascii=False, indent=2)}\n\n"
        f"User instructions: {instructions}\n\n"
        "Apply the instructions and return the updated taxonomy JSON."
    )
    fn = chat_fn or chat
    raw = fn(MODIFY_TAXONOMY_SYSTEM, user_prompt)
    return json.loads(_strip_fences(raw))
