from __future__ import annotations

import time
from typing import Callable

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

from atria.core.auth.keycloak.config import KeycloakConfig


class InvalidTokenError(Exception):
    pass


class JwksCache:
    """Caches JWKS keys, fetched lazily; TTL-bounded."""

    def __init__(self, cfg: KeycloakConfig, fetcher: Callable[[], dict] | None = None) -> None:
        self._cfg = cfg
        self._fetcher = fetcher or self._default_fetcher
        self._keys: dict[str, object] = {}
        self._fetched_at: float = 0.0

    def _default_fetcher(self) -> dict:
        resp = httpx.get(self._cfg.jwks_url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def _refresh(self) -> None:
        jwks = self._fetcher()
        self._keys = {k["kid"]: RSAAlgorithm.from_jwk(k) for k in jwks.get("keys", [])}
        self._fetched_at = time.time()

    def get_key(self, kid: str):
        ttl = self._cfg.jwks_cache_ttl_seconds
        if not self._keys or (time.time() - self._fetched_at) >= ttl:
            self._refresh()
        if kid not in self._keys:
            # Key may have rotated; force one refresh.
            self._refresh()
        if kid not in self._keys:
            raise InvalidTokenError(f"Unknown signing key kid={kid}")
        return self._keys[kid]


class TokenValidator:
    def __init__(self, cfg: KeycloakConfig, cache: JwksCache) -> None:
        self._cfg = cfg
        self._cache = cache

    def validate(self, token: str) -> dict:
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc
        kid = header.get("kid")
        if not kid:
            raise InvalidTokenError("Token missing kid header")
        key = self._cache.get_key(kid)
        try:
            return pyjwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._cfg.issuer,
                options={
                    "verify_aud": False
                },  # Keycloak audience varies; we check claims separately
            )
        except pyjwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc
