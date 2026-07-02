"""Thin OpenAI-compatible client that dispatches calls by feature role.

One underlying ``openai.OpenAI`` is created per distinct (base_url, api_key)
so TEI and vLLM endpoints are reused across roles that share them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from typing import Callable, Dict, List, Optional, Tuple

try:  # Import lazily so unit tests can inject a fake factory without openai.
    from openai import OpenAI as _OpenAI
except ImportError:  # pragma: no cover - openai installed in real env
    _OpenAI = None  # type: ignore[assignment]

from config import RoleConfig  # type: ignore[import-not-found]

ClientFactory = Callable[[str, str], object]


def _default_factory(base_url: str, api_key: str) -> object:
    if _OpenAI is None:  # pragma: no cover
        raise RuntimeError("openai package is not installed")
    return _OpenAI(base_url=base_url, api_key=api_key)


class RoleClient:
    """Resolve embed/chat calls to the endpoint configured for a role."""

    def __init__(
        self,
        config: Dict[str, RoleConfig],
        client_factory: Optional[ClientFactory] = None,
    ) -> None:
        self._config = config
        self._factory = client_factory or _default_factory
        self._clients: Dict[Tuple[str, str], object] = {}

    def _role(self, role: str) -> RoleConfig:
        if role not in self._config:
            raise ValueError(f"unknown role: {role!r}")
        return self._config[role]

    def _client_for(self, rc: RoleConfig) -> object:
        key = (rc.base_url, rc.api_key)
        if key not in self._clients:
            self._clients[key] = self._factory(rc.base_url, rc.api_key)
        return self._clients[key]

    def embed(self, role: str, texts: List[str]) -> List[List[float]]:
        """Return embedding vectors for *texts* using the endpoint for *role*.

        Args:
            role: Feature role key (e.g. ``"chunk_embed"``, ``"index_embed"``).
            texts: One or more strings to embed.

        Returns:
            A list of float vectors, one per input text, in the same order.
        """
        rc = self._role(role)
        client = self._client_for(rc)
        resp = client.embeddings.create(model=rc.model, input=texts)  # type: ignore[attr-defined]
        return [item.embedding for item in resp.data]

    def chat(self, role: str, messages: List[dict], **kw) -> str:
        """Send a chat-completion request using the endpoint configured for *role*.

        Args:
            role: Feature role key (e.g. ``"synthesis"``, ``"kg_extract"``).
            messages: OpenAI-format message list (``[{"role": ..., "content": ...}, ...]``).
            **kw: Extra keyword arguments forwarded to ``completions.create``
                (e.g. ``temperature``, ``max_tokens``).

        Returns:
            The text content of the first choice's message.
        """
        rc = self._role(role)
        client = self._client_for(rc)
        resp = client.chat.completions.create(  # type: ignore[attr-defined]
            model=rc.model, messages=messages, **kw
        )
        return resp.choices[0].message.content
