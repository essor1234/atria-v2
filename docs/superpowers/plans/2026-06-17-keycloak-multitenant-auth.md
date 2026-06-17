# Keycloak Multi-Tenant Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Keycloak to the docker-compose stack and integrate OIDC-based multi-tenant auth into FastAPI + web-ui, with a thin admin UI for tenant and user management.

**Architecture:** Single Keycloak realm `atria` where tenants are realm groups (`/tenants/<slug>`) and roles are `tenant:<slug>:<admin|member>`. The SPA does OIDC Authorization Code + PKCE against Keycloak and sends bearer JWTs to FastAPI along with an `X-Atria-Tenant` header to select the active tenant. FastAPI validates JWTs via cached JWKS, resolves the principal, and calls the Keycloak Admin API (via a confidential client's service account) for admin operations. An `AUTH_MODE=keycloak|none` env var lets the existing cookie-based flow keep working when Keycloak is not running.

**Tech Stack:** Keycloak 26 (image `quay.io/keycloak/keycloak:26.0`) backed by the existing Postgres container, Python `httpx` + `pyjwt` (with `cryptography`) for token validation and Admin API, FastAPI dependencies for principal resolution, React + `oidc-client-ts` for the SPA flow.

**Spec reference:** `docs/superpowers/specs/2026-06-17-keycloak-multitenant-auth-design.md`

---

## File Structure

**Backend (new):**
- `atria/core/auth/keycloak/__init__.py` — package marker.
- `atria/core/auth/keycloak/config.py` — env-driven settings (URL, realm, client IDs, secret, JWKS cache TTL, `AUTH_MODE`).
- `atria/core/auth/keycloak/jwt.py` — JWKS fetch + cache, JWT decode/verify, claim extraction.
- `atria/core/auth/keycloak/principal.py` — `CurrentPrincipal` dataclass, `get_current_principal` FastAPI dep, `require_role` factory.
- `atria/core/auth/keycloak/admin_client.py` — `httpx`-based Admin API wrapper with service-account token cache.
- `atria/web/routes/admin_tenants.py` — tenant CRUD endpoints.
- `atria/web/routes/admin_tenant_users.py` — tenant user invite/role/remove endpoints.
- `atria/web/routes/me.py` — `/api/me` returning principal + tenant list.

**Backend (modified):**
- `atria/web/dependencies/auth.py` — branch on `AUTH_MODE`; in `keycloak` mode delegate to `get_current_principal` and lazy-sync the Keycloak `sub` into a `User` row so existing endpoints stay compatible.
- `atria/web/server.py` (or wherever routers register) — include the three new routers.
- `pyproject.toml` — add `pyjwt[crypto]>=2.8` and `httpx` (verify already present).

**Frontend (new):**
- `web-ui/src/auth/oidc.ts` — `UserManager` setup, login/logout/refresh, token store.
- `web-ui/src/auth/AuthProvider.tsx` — React context, login redirect handling, `useAuth()` hook.
- `web-ui/src/auth/apiClient.ts` — fetch wrapper that injects `Authorization: Bearer …` and `X-Atria-Tenant`.
- `web-ui/src/stores/tenantStore.ts` — Zustand store for active tenant + tenant list.
- `web-ui/src/components/TenantSwitcher.tsx` — dropdown in the layout header.
- `web-ui/src/pages/admin/TenantsPage.tsx` — super-admin tenant CRUD.
- `web-ui/src/pages/admin/TenantUsersPage.tsx` — tenant-scoped user mgmt.

**Frontend (modified):**
- `web-ui/src/App.tsx` — wrap in `AuthProvider`, add `/admin/*` routes.
- `web-ui/src/api/*` — switch fetches to the new `apiClient` (mechanical).

**Infra (new):**
- `keycloak/realm-export.json` — bootstrap realm definition.

**Infra (modified):**
- `schema.sql` — add `CREATE DATABASE keycloak;`.
- `docker-compose.yml` — add `keycloak` service, env on `atria`.

**Tests (new):**
- `tests/core/auth/test_keycloak_jwt.py`
- `tests/core/auth/test_keycloak_principal.py`
- `tests/core/auth/test_keycloak_admin_client.py`
- `tests/web/test_admin_tenants_routes.py`
- `tests/web/test_admin_tenant_users_routes.py`
- `tests/web/test_me_route.py`
- `tests/integration/test_auth_keycloak.py` — real Keycloak container.

---

## Task 1: Backend config module + AUTH_MODE plumbing

**Files:**
- Create: `atria/core/auth/keycloak/__init__.py`
- Create: `atria/core/auth/keycloak/config.py`
- Create: `tests/core/auth/__init__.py` (empty)
- Create: `tests/core/auth/test_keycloak_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/auth/test_keycloak_config.py
import os

import pytest

from atria.core.auth.keycloak.config import KeycloakConfig, AuthMode


def test_defaults_to_auth_mode_none(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    cfg = KeycloakConfig.from_env()
    assert cfg.auth_mode is AuthMode.NONE


def test_loads_keycloak_settings(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak:8080")
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082")
    monkeypatch.setenv("KEYCLOAK_REALM", "atria")
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend")
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_SECRET", "shh")
    cfg = KeycloakConfig.from_env()
    assert cfg.auth_mode is AuthMode.KEYCLOAK
    assert cfg.realm == "atria"
    assert cfg.issuer == "http://localhost:8082/realms/atria"
    assert cfg.jwks_url == "http://keycloak:8080/realms/atria/protocol/openid-connect/certs"
    assert cfg.token_url == "http://keycloak:8080/realms/atria/protocol/openid-connect/token"
    assert cfg.admin_base_url == "http://keycloak:8080/admin/realms/atria"
    assert cfg.backend_client_id == "atria-backend"
    assert cfg.backend_client_secret == "shh"


def test_keycloak_mode_requires_secret(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.delenv("KEYCLOAK_BACKEND_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="KEYCLOAK_BACKEND_CLIENT_SECRET"):
        KeycloakConfig.from_env()
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/core/auth/test_keycloak_config.py -v
```
Expected: ImportError / ModuleNotFoundError on `atria.core.auth.keycloak.config`.

- [ ] **Step 3: Create the package marker**

```python
# atria/core/auth/keycloak/__init__.py
"""Keycloak integration (config, JWT, principal, admin client)."""
```

- [ ] **Step 4: Implement config**

```python
# atria/core/auth/keycloak/config.py
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class AuthMode(str, Enum):
    NONE = "none"
    KEYCLOAK = "keycloak"


@dataclass(frozen=True)
class KeycloakConfig:
    auth_mode: AuthMode
    internal_url: str          # used by backend ↔ keycloak (e.g. http://keycloak:8080)
    public_url: str            # used for issuer matching (e.g. http://localhost:8082)
    realm: str
    backend_client_id: str
    backend_client_secret: str
    jwks_cache_ttl_seconds: int = 300

    @property
    def issuer(self) -> str:
        return f"{self.public_url.rstrip('/')}/realms/{self.realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def admin_base_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/admin/realms/{self.realm}"

    @classmethod
    def from_env(cls) -> "KeycloakConfig":
        mode_raw = os.getenv("AUTH_MODE", "none").lower()
        mode = AuthMode(mode_raw) if mode_raw in {m.value for m in AuthMode} else AuthMode.NONE

        if mode is AuthMode.NONE:
            return cls(
                auth_mode=mode,
                internal_url="",
                public_url="",
                realm="",
                backend_client_id="",
                backend_client_secret="",
            )

        secret = os.getenv("KEYCLOAK_BACKEND_CLIENT_SECRET", "")
        if not secret:
            raise RuntimeError("KEYCLOAK_BACKEND_CLIENT_SECRET is required when AUTH_MODE=keycloak")

        return cls(
            auth_mode=mode,
            internal_url=os.getenv("KEYCLOAK_URL", "http://keycloak:8080"),
            public_url=os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082"),
            realm=os.getenv("KEYCLOAK_REALM", "atria"),
            backend_client_id=os.getenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend"),
            backend_client_secret=secret,
        )
```

- [ ] **Step 5: Run test to verify pass**

```bash
uv run pytest tests/core/auth/test_keycloak_config.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add atria/core/auth/keycloak/__init__.py atria/core/auth/keycloak/config.py tests/core/auth/__init__.py tests/core/auth/test_keycloak_config.py
git commit -m "feat(auth): keycloak config module with AUTH_MODE switch"
```

---

## Task 2: JWT validator with JWKS cache

**Files:**
- Create: `atria/core/auth/keycloak/jwt.py`
- Create: `tests/core/auth/test_keycloak_jwt.py`
- Modify: `pyproject.toml` (add `pyjwt[crypto]>=2.8`)

- [ ] **Step 1: Add dependency**

Edit `pyproject.toml` `[project] dependencies` (or `dependencies = [...]`) — add `"pyjwt[crypto]>=2.8"`. Run:

```bash
uv lock && uv sync
```

- [ ] **Step 2: Write the failing test**

```python
# tests/core/auth/test_keycloak_jwt.py
import time
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import JwksCache, TokenValidator, InvalidTokenError


def _make_cfg() -> KeycloakConfig:
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
        jwks_cache_ttl_seconds=60,
    )


def _generate_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_numbers = key.public_key().public_numbers()
    import base64

    def b64url_uint(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": b64url_uint(pub_numbers.n),
        "e": b64url_uint(pub_numbers.e),
    }
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, jwk


def _sign(payload: dict, pem: bytes) -> str:
    return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": "test-key"})


def test_validator_accepts_valid_token():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {
            "iss": cfg.issuer,
            "sub": "user-1",
            "aud": "account",
            "exp": now + 60,
            "iat": now,
            "email": "a@b.c",
            "preferred_username": "a",
            "groups": ["/tenants/acme"],
            "realm_access": {"roles": ["tenant:acme:admin"]},
        },
        pem,
    )
    claims = validator.validate(token)
    assert claims["sub"] == "user-1"
    assert claims["groups"] == ["/tenants/acme"]


def test_validator_rejects_wrong_issuer():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {"iss": "http://evil/realms/atria", "sub": "x", "aud": "account", "exp": now + 60, "iat": now},
        pem,
    )
    with pytest.raises(InvalidTokenError):
        validator.validate(token)


def test_validator_rejects_expired_token():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {"iss": cfg.issuer, "sub": "x", "aud": "account", "exp": now - 5, "iat": now - 60},
        pem,
    )
    with pytest.raises(InvalidTokenError):
        validator.validate(token)


def test_jwks_cache_refetches_after_ttl():
    pem, jwk = _generate_keypair()
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
        jwks_cache_ttl_seconds=0,
    )
    calls = MagicMock(return_value={"keys": [jwk]})
    cache = JwksCache(cfg, fetcher=calls)
    cache.get_key("test-key")
    cache.get_key("test-key")
    assert calls.call_count == 2
```

- [ ] **Step 3: Run test to verify failure**

```bash
uv run pytest tests/core/auth/test_keycloak_jwt.py -v
```
Expected: ImportError on `atria.core.auth.keycloak.jwt`.

- [ ] **Step 4: Implement JWT validator**

```python
# atria/core/auth/keycloak/jwt.py
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
                options={"verify_aud": False},  # Keycloak audience varies; we check claims separately
            )
        except pyjwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/core/auth/test_keycloak_jwt.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add atria/core/auth/keycloak/jwt.py tests/core/auth/test_keycloak_jwt.py pyproject.toml uv.lock
git commit -m "feat(auth): keycloak JWT validator with JWKS cache"
```

---

## Task 3: Principal model + `require_role` dependency

**Files:**
- Create: `atria/core/auth/keycloak/principal.py`
- Create: `tests/core/auth/test_keycloak_principal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/auth/test_keycloak_principal.py
import pytest

from atria.core.auth.keycloak.principal import (
    CurrentPrincipal,
    PrincipalResolutionError,
    build_principal,
)


def _claims(groups, roles):
    return {
        "sub": "user-uuid",
        "email": "a@b.c",
        "preferred_username": "alice",
        "groups": groups,
        "realm_access": {"roles": roles},
    }


def test_builds_member_principal_for_tenant():
    p = build_principal(_claims(["/tenants/acme"], ["tenant:acme:member"]), "acme")
    assert isinstance(p, CurrentPrincipal)
    assert p.user_id == "user-uuid"
    assert p.tenant_id == "acme"
    assert p.tenant_role == "member"
    assert p.is_platform_admin is False


def test_platform_admin_flag():
    p = build_principal(_claims(["/tenants/acme"], ["platform:admin", "tenant:acme:admin"]), "acme")
    assert p.is_platform_admin is True
    assert p.tenant_role == "admin"


def test_rejects_user_not_in_tenant_group():
    with pytest.raises(PrincipalResolutionError):
        build_principal(_claims(["/tenants/other"], ["tenant:other:admin"]), "acme")


def test_no_tenant_role_means_member_fallback_is_rejected():
    # If user is in the group but has no role, we deny — explicit roles only.
    with pytest.raises(PrincipalResolutionError):
        build_principal(_claims(["/tenants/acme"], []), "acme")


def test_platform_admin_can_access_any_tenant_without_membership():
    p = build_principal(_claims([], ["platform:admin"]), "acme")
    assert p.is_platform_admin is True
    assert p.tenant_id == "acme"
    assert p.tenant_role == "admin"
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/core/auth/test_keycloak_principal.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# atria/core/auth/keycloak/principal.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

PLATFORM_ADMIN_ROLE = "platform:admin"
_TENANT_ROLE_RE = re.compile(r"^tenant:([^:]+):(admin|member)$")


class PrincipalResolutionError(Exception):
    """Raised when a token cannot be resolved into a principal for the requested tenant."""


@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: str
    email: str
    username: str
    tenant_id: str
    tenant_role: str           # "admin" or "member"
    is_platform_admin: bool
    raw_groups: tuple[str, ...]
    raw_roles: tuple[str, ...]


def _extract_tenant_role(roles: list[str], tenant_id: str) -> Optional[str]:
    for r in roles:
        m = _TENANT_ROLE_RE.match(r)
        if m and m.group(1) == tenant_id:
            return m.group(2)
    return None


def build_principal(claims: dict, requested_tenant: str) -> CurrentPrincipal:
    groups = list(claims.get("groups", []))
    roles = list(claims.get("realm_access", {}).get("roles", []))
    is_platform_admin = PLATFORM_ADMIN_ROLE in roles

    in_group = f"/tenants/{requested_tenant}" in groups
    tenant_role = _extract_tenant_role(roles, requested_tenant)

    if is_platform_admin:
        effective_role = tenant_role or "admin"
    else:
        if not in_group:
            raise PrincipalResolutionError(
                f"User is not a member of tenant '{requested_tenant}'"
            )
        if not tenant_role:
            raise PrincipalResolutionError(
                f"User has no role in tenant '{requested_tenant}'"
            )
        effective_role = tenant_role

    return CurrentPrincipal(
        user_id=claims["sub"],
        email=claims.get("email", ""),
        username=claims.get("preferred_username", ""),
        tenant_id=requested_tenant,
        tenant_role=effective_role,
        is_platform_admin=is_platform_admin,
        raw_groups=tuple(groups),
        raw_roles=tuple(roles),
    )
```

- [ ] **Step 4: Run to pass**

```bash
uv run pytest tests/core/auth/test_keycloak_principal.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add atria/core/auth/keycloak/principal.py tests/core/auth/test_keycloak_principal.py
git commit -m "feat(auth): CurrentPrincipal builder for Keycloak claims"
```

---

## Task 4: FastAPI dependency `get_current_principal` and `require_role`

**Files:**
- Modify: `atria/core/auth/keycloak/principal.py` (append FastAPI deps)
- Create: `tests/core/auth/test_keycloak_deps.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/auth/test_keycloak_deps.py
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Depends
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import InvalidTokenError
from atria.core.auth.keycloak.principal import (
    CurrentPrincipal,
    get_current_principal_factory,
    require_role,
)


def _cfg():
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
    )


def _claims(groups, roles):
    return {
        "sub": "user-uuid",
        "email": "a@b.c",
        "preferred_username": "alice",
        "groups": groups,
        "realm_access": {"roles": roles},
    }


def _make_app(validator):
    cfg = _cfg()
    dep = get_current_principal_factory(cfg, validator)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(p: CurrentPrincipal = Depends(dep)):
        return {"user": p.user_id, "tenant": p.tenant_id, "role": p.tenant_role}

    @app.get("/admin-only")
    def admin_only(
        p: CurrentPrincipal = Depends(dep),
        _: None = Depends(require_role("platform:admin")),
    ):
        return {"ok": True}

    return app


def test_401_without_bearer():
    validator = MagicMock()
    client = TestClient(_make_app(validator))
    r = client.get("/whoami", headers={"X-Atria-Tenant": "acme"})
    assert r.status_code == 401


def test_403_when_user_not_in_tenant():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/other"], ["tenant:other:admin"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_200_when_member():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"user": "user-uuid", "tenant": "acme", "role": "member"}


def test_401_when_token_invalid():
    validator = MagicMock()
    validator.validate.side_effect = InvalidTokenError("bad sig")
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 401


def test_require_role_platform_admin_blocks_member():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/admin-only",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_require_role_platform_admin_allows_admin():
    validator = MagicMock()
    validator.validate.return_value = _claims([], ["platform:admin"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/admin-only",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200


def test_missing_tenant_header_returns_400():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get("/whoami", headers={"Authorization": "Bearer x"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/core/auth/test_keycloak_deps.py -v
```
Expected: ImportError on `get_current_principal_factory` / `require_role`.

- [ ] **Step 3: Append FastAPI dependency helpers**

Append to `atria/core/auth/keycloak/principal.py`:

```python
# --- FastAPI integration ---------------------------------------------------

from fastapi import HTTPException, Request, status, Depends
from typing import Callable

from atria.core.auth.keycloak.config import KeycloakConfig
from atria.core.auth.keycloak.jwt import InvalidTokenError, TokenValidator


def _extract_bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return auth.split(" ", 1)[1].strip()


def get_current_principal_factory(
    cfg: KeycloakConfig, validator: TokenValidator
) -> Callable[[Request], CurrentPrincipal]:
    def dep(request: Request) -> CurrentPrincipal:
        token = _extract_bearer(request)
        tenant = request.headers.get("X-Atria-Tenant", "").strip()
        if not tenant:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Atria-Tenant header required")
        try:
            claims = validator.validate(token)
        except InvalidTokenError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
        try:
            principal = build_principal(claims, tenant)
        except PrincipalResolutionError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
        request.state.principal = principal
        return principal
    return dep


def require_role(role: str) -> Callable[[Request], None]:
    """Require either a literal role like 'platform:admin' or 'tenant_admin'.

    'tenant_admin' is interpreted as: the principal must be admin in their active tenant
    OR a platform admin.
    """

    def dep(request: Request) -> None:
        p: CurrentPrincipal | None = getattr(request.state, "principal", None)
        if p is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Principal not resolved")
        if role == "platform:admin":
            if not p.is_platform_admin:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admin only")
            return
        if role == "tenant_admin":
            if p.is_platform_admin or p.tenant_role == "admin":
                return
            raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")
        # Literal realm role
        if role in p.raw_roles:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"role '{role}' required")

    return dep
```

- [ ] **Step 4: Run to pass**

```bash
uv run pytest tests/core/auth/test_keycloak_deps.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add atria/core/auth/keycloak/principal.py tests/core/auth/test_keycloak_deps.py
git commit -m "feat(auth): FastAPI deps for Keycloak principal + require_role"
```

---

## Task 5: Keycloak Admin API client

**Files:**
- Create: `atria/core/auth/keycloak/admin_client.py`
- Create: `tests/core/auth/test_keycloak_admin_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/auth/test_keycloak_admin_client.py
import time

import httpx
import pytest

from atria.core.auth.keycloak.admin_client import KeycloakAdminClient, TenantSpec
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig


def _cfg():
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
    )


def _mock_transport(routes):
    """routes: list of (method, url_predicate, response_factory)."""
    def handler(request: httpx.Request) -> httpx.Response:
        for method, pred, factory in routes:
            if request.method == method and pred(request.url.path):
                return factory(request)
        return httpx.Response(404, json={"path": request.url.path})
    return httpx.MockTransport(handler)


def test_acquires_service_account_token_lazily():
    calls = {"token": 0, "groups": 0}

    def token_response(req):
        calls["token"] += 1
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def groups_response(req):
        calls["groups"] += 1
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json=[])

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token_response),
        ("GET", lambda p: p.endswith("/groups"), groups_response),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.list_tenant_groups()
    client.list_tenant_groups()
    assert calls["token"] == 1  # token cached
    assert calls["groups"] == 2


def test_create_tenant_creates_group_and_roles():
    seen = []

    def token(req):
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def post_groups(req):
        seen.append(("group", req.read().decode()))
        return httpx.Response(201, headers={"Location": "http://kc/admin/realms/atria/groups/G1"})

    def post_roles(req):
        seen.append(("role", req.read().decode()))
        return httpx.Response(201)

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token),
        ("POST", lambda p: p.endswith("/groups"), post_groups),
        ("POST", lambda p: p.endswith("/roles"), post_roles),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.create_tenant(TenantSpec(slug="acme", name="Acme Inc"))
    kinds = [k for k, _ in seen]
    assert kinds == ["group", "role", "role"]


def test_delete_tenant_deletes_group_and_roles():
    def token(req):
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def get_group_by_path(req):
        # Path: /groups?search=acme — return the group id
        return httpx.Response(200, json=[{"id": "G1", "name": "acme", "path": "/tenants/acme"}])

    deleted = []

    def delete_group(req):
        deleted.append(("group", req.url.path))
        return httpx.Response(204)

    def delete_role(req):
        deleted.append(("role", req.url.path))
        return httpx.Response(204)

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token),
        ("GET", lambda p: p.endswith("/groups"), get_group_by_path),
        ("DELETE", lambda p: "/groups/G1" in p, delete_group),
        ("DELETE", lambda p: "/roles/tenant:acme:" in p, delete_role),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.delete_tenant("acme")
    kinds = [k for k, _ in deleted]
    assert kinds.count("role") == 2
    assert kinds.count("group") == 1
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/core/auth/test_keycloak_admin_client.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement client**

```python
# atria/core/auth/keycloak/admin_client.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from atria.core.auth.keycloak.config import KeycloakConfig


@dataclass(frozen=True)
class TenantSpec:
    slug: str
    name: str


@dataclass(frozen=True)
class TenantSummary:
    id: str
    slug: str
    name: str


@dataclass(frozen=True)
class TenantUser:
    user_id: str
    username: str
    email: str
    role: str  # "admin" or "member"


class KeycloakAdminClient:
    """Thin sync wrapper around the Keycloak Admin REST API.

    The service account token is cached until ~30s before expiry.
    Uses sync httpx to keep call sites simple; admin operations are infrequent.
    """

    def __init__(self, cfg: KeycloakConfig, transport: Optional[httpx.BaseTransport] = None) -> None:
        self._cfg = cfg
        self._client = httpx.Client(timeout=10.0, transport=transport)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # --- auth -------------------------------------------------------------
    def _fetch_token(self) -> str:
        resp = self._client.post(
            self._cfg.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._cfg.backend_client_id,
                "client_secret": self._cfg.backend_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + max(int(payload.get("expires_in", 60)) - 30, 10)
        return self._token

    def _auth_header(self) -> dict[str, str]:
        if not self._token or time.time() >= self._token_expiry:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        url = f"{self._cfg.admin_base_url}{path}"
        headers = {**self._auth_header(), **kw.pop("headers", {})}
        resp = self._client.request(method, url, headers=headers, **kw)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{method} {path} -> {resp.status_code}: {resp.text}",
                request=resp.request,
                response=resp,
            )
        return resp

    # --- tenants ----------------------------------------------------------
    def list_tenant_groups(self) -> list[TenantSummary]:
        resp = self._req("GET", "/groups", params={"search": "tenants"})
        out: list[TenantSummary] = []
        for g in resp.json():
            if g.get("name") == "tenants":
                for sub in g.get("subGroups", []):
                    out.append(TenantSummary(id=sub["id"], slug=sub["name"], name=sub.get("attributes", {}).get("displayName", [sub["name"]])[0]))
        return out

    def create_tenant(self, spec: TenantSpec) -> None:
        # Create top-level group /tenants/<slug>. We assume /tenants exists (seeded in realm-export).
        # Find the /tenants parent id.
        parents = self._req("GET", "/groups", params={"search": "tenants"}).json()
        parent_id = next((g["id"] for g in parents if g["name"] == "tenants"), None)
        if not parent_id:
            raise RuntimeError("Parent group /tenants is missing from realm")
        self._req(
            "POST",
            f"/groups/{parent_id}/children",
            json={"name": spec.slug, "attributes": {"displayName": [spec.name]}},
        )
        for role in (f"tenant:{spec.slug}:admin", f"tenant:{spec.slug}:member"):
            self._req("POST", "/roles", json={"name": role})

    def _find_tenant_group_id(self, slug: str) -> str:
        # Look up by path search.
        resp = self._req("GET", "/groups", params={"search": slug})
        for g in resp.json():
            if g.get("name") == slug and g.get("path") == f"/tenants/{slug}":
                return g["id"]
            for sub in g.get("subGroups", []):
                if sub.get("path") == f"/tenants/{slug}":
                    return sub["id"]
        raise LookupError(f"Tenant '{slug}' not found")

    def delete_tenant(self, slug: str) -> None:
        gid = self._find_tenant_group_id(slug)
        self._req("DELETE", f"/groups/{gid}")
        for role in (f"tenant:{slug}:admin", f"tenant:{slug}:member"):
            try:
                self._req("DELETE", f"/roles/{role}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

    # --- tenant users -----------------------------------------------------
    def list_tenant_users(self, slug: str) -> list[TenantUser]:
        gid = self._find_tenant_group_id(slug)
        members = self._req("GET", f"/groups/{gid}/members").json()
        out: list[TenantUser] = []
        for m in members:
            roles = self._req("GET", f"/users/{m['id']}/role-mappings/realm").json()
            role_names = {r["name"] for r in roles}
            if f"tenant:{slug}:admin" in role_names:
                role = "admin"
            elif f"tenant:{slug}:member" in role_names:
                role = "member"
            else:
                role = "member"
            out.append(TenantUser(user_id=m["id"], username=m.get("username", ""), email=m.get("email", ""), role=role))
        return out

    def invite_user(self, slug: str, email: str, role: str) -> str:
        """Create user if missing, add to group, assign role, send verify-email action.

        Returns the user_id.
        """
        existing = self._req("GET", "/users", params={"email": email, "exact": "true"}).json()
        if existing:
            user_id = existing[0]["id"]
        else:
            self._req(
                "POST",
                "/users",
                json={"email": email, "username": email, "enabled": True, "emailVerified": False},
            )
            user_id = self._req("GET", "/users", params={"email": email, "exact": "true"}).json()[0]["id"]

        gid = self._find_tenant_group_id(slug)
        self._req("PUT", f"/users/{user_id}/groups/{gid}")
        self._assign_role(user_id, f"tenant:{slug}:{role}")
        # Send invite email with required actions
        self._req(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            json=["VERIFY_EMAIL", "UPDATE_PASSWORD"],
        )
        return user_id

    def set_user_role(self, slug: str, user_id: str, new_role: str) -> None:
        # Remove the opposite role first if present, then assign new.
        opposite = "member" if new_role == "admin" else "admin"
        self._unassign_role(user_id, f"tenant:{slug}:{opposite}")
        self._assign_role(user_id, f"tenant:{slug}:{new_role}")

    def remove_user_from_tenant(self, slug: str, user_id: str) -> None:
        gid = self._find_tenant_group_id(slug)
        try:
            self._req("DELETE", f"/users/{user_id}/groups/{gid}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        for role in (f"tenant:{slug}:admin", f"tenant:{slug}:member"):
            self._unassign_role(user_id, role)

    def _role_repr(self, role_name: str) -> dict:
        return self._req("GET", f"/roles/{role_name}").json()

    def _assign_role(self, user_id: str, role_name: str) -> None:
        role = self._role_repr(role_name)
        self._req("POST", f"/users/{user_id}/role-mappings/realm", json=[role])

    def _unassign_role(self, user_id: str, role_name: str) -> None:
        try:
            role = self._role_repr(role_name)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return
            raise
        try:
            self._req("DELETE", f"/users/{user_id}/role-mappings/realm", json=[role])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/core/auth/test_keycloak_admin_client.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add atria/core/auth/keycloak/admin_client.py tests/core/auth/test_keycloak_admin_client.py
git commit -m "feat(auth): keycloak admin API client (tenants + users)"
```

---

## Task 6: Wire shared `KeycloakServices` into web state and switch `require_authenticated_user`

**Files:**
- Modify: `atria/web/state.py` (add lazily-built `KeycloakServices`)
- Modify: `atria/web/dependencies/auth.py` (branch on AUTH_MODE)
- Create: `tests/web/test_dependencies_auth_keycloak.py`

This task wires the modules built so far into the existing FastAPI app and adds the lazy `User`-row sync.

- [ ] **Step 1: Inspect current `atria/web/state.py`**

```bash
grep -n "class WebState\|def get_state\|user_store" atria/web/state.py | head -20
```
You will see a `WebState` class. We will add `keycloak: KeycloakServices | None` lazy-built from env.

- [ ] **Step 2: Create the services bundle**

Add to a new file `atria/core/auth/keycloak/services.py`:

```python
# atria/core/auth/keycloak/services.py
from __future__ import annotations

from dataclasses import dataclass

from atria.core.auth.keycloak.admin_client import KeycloakAdminClient
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import JwksCache, TokenValidator


@dataclass(frozen=True)
class KeycloakServices:
    config: KeycloakConfig
    validator: TokenValidator
    admin: KeycloakAdminClient

    @classmethod
    def from_env(cls) -> "KeycloakServices | None":
        cfg = KeycloakConfig.from_env()
        if cfg.auth_mode is not AuthMode.KEYCLOAK:
            return None
        cache = JwksCache(cfg)
        validator = TokenValidator(cfg, cache)
        admin = KeycloakAdminClient(cfg)
        return cls(config=cfg, validator=validator, admin=admin)
```

Commit-block files: add this file.

- [ ] **Step 3: Modify `WebState`**

In `atria/web/state.py`, add to imports:

```python
from atria.core.auth.keycloak.services import KeycloakServices
```

Add a class attribute / field initialized at construction:

```python
self.keycloak: KeycloakServices | None = KeycloakServices.from_env()
```

(Inspect the surrounding constructor and add this in the same style as `user_store`.)

- [ ] **Step 4: Write the failing test for the branched dep**

```python
# tests/web/test_dependencies_auth_keycloak.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web.dependencies.auth import require_authenticated_user
from atria.web import state as state_module


@pytest.fixture
def app_with_keycloak(monkeypatch):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid-1",
        "email": "alice@acme.test",
        "preferred_username": "alice",
        "groups": ["/tenants/acme"],
        "realm_access": {"roles": ["tenant:acme:member"]},
    }
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="x",
        backend_client_secret="y",
    )
    services = KeycloakServices(config=cfg, validator=validator, admin=MagicMock())

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(return_value=None)
    user_store.create_user = AsyncMock(return_value=User(id=42, username="alice", email="alice@acme.test"))

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store

    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)

    app = FastAPI()

    @app.get("/probe")
    async def probe(user: User = Depends(require_authenticated_user)):
        return {"id": user.id, "email": user.email}

    return app, user_store


def test_keycloak_mode_lazy_creates_user(app_with_keycloak):
    app, store = app_with_keycloak
    client = TestClient(app)
    r = client.get(
        "/probe",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"id": 42, "email": "alice@acme.test"}
    store.create_user.assert_awaited_once()


def test_keycloak_mode_missing_bearer_returns_401(app_with_keycloak):
    app, _ = app_with_keycloak
    client = TestClient(app)
    r = client.get("/probe", headers={"X-Atria-Tenant": "acme"})
    assert r.status_code == 401
```

- [ ] **Step 5: Run to fail**

```bash
uv run pytest tests/web/test_dependencies_auth_keycloak.py -v
```
Expected: assertion / 200 failure because current `require_authenticated_user` falls back to anonymous.

- [ ] **Step 6: Rewrite `atria/web/dependencies/auth.py`**

```python
# atria/web/dependencies/auth.py
"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from atria.core.auth.keycloak.jwt import InvalidTokenError
from atria.core.auth.keycloak.principal import (
    PrincipalResolutionError,
    build_principal,
)
from atria.models.user import User
from atria.web.routes.auth import TOKEN_COOKIE, verify_token
from atria.web.state import get_state

_ANONYMOUS_USER: User | None = None


def _get_anonymous_user() -> User:
    global _ANONYMOUS_USER
    if _ANONYMOUS_USER is None:
        _ANONYMOUS_USER = User(id=0, username="local", email="local@localhost")
    return _ANONYMOUS_USER


async def _resolve_keycloak_user(request: Request) -> User:
    state = get_state()
    services = state.keycloak
    assert services is not None  # callers must check first

    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = auth.split(" ", 1)[1].strip()

    tenant = request.headers.get("X-Atria-Tenant", "").strip()
    if not tenant:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Atria-Tenant header required")

    try:
        claims = services.validator.validate(token)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc

    try:
        principal = build_principal(claims, tenant)
    except PrincipalResolutionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    # Lazy-sync into the Atria user table so legacy endpoints that take User keep working.
    user_store = state.user_store
    user = await user_store.get_by_email(principal.email) if principal.email else None
    if not user:
        username = principal.username or (principal.email.split("@")[0] if principal.email else principal.user_id[:8])
        user = await user_store.create_user(username=username, password_hash="", email=principal.email)

    request.state.principal = principal
    request.state.user = user
    return user


async def require_authenticated_user(request: Request) -> User:
    """Resolve a user via Keycloak when configured; else fall back to the legacy cookie/anonymous path."""

    state = get_state()
    if getattr(state, "keycloak", None) is not None:
        return await _resolve_keycloak_user(request)

    # Legacy cookie / anonymous path (unchanged).
    token = request.cookies.get(TOKEN_COOKIE)
    if not token:
        user = _get_anonymous_user()
        request.state.user = user
        return user

    try:
        user_id_str = verify_token(token)
        user = await state.user_store.get_by_id(int(user_id_str))
        if not user:
            user = _get_anonymous_user()
        request.state.user = user
        return user
    except Exception:
        user = _get_anonymous_user()
        request.state.user = user
        return user
```

- [ ] **Step 7: Run all auth tests**

```bash
uv run pytest tests/web/test_dependencies_auth_keycloak.py tests/core/auth -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add atria/core/auth/keycloak/services.py atria/web/state.py atria/web/dependencies/auth.py tests/web/test_dependencies_auth_keycloak.py
git commit -m "feat(auth): wire Keycloak into WebState and require_authenticated_user"
```

---

## Task 7: `/api/me` route

**Files:**
- Create: `atria/web/routes/me.py`
- Modify: `atria/web/server.py` (register router)
- Create: `tests/web/test_me_route.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_me_route.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web import state as state_module
from atria.web.routes.me import router as me_router


@pytest.fixture
def client(monkeypatch):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid",
        "email": "alice@acme.test",
        "preferred_username": "alice",
        "groups": ["/tenants/acme", "/tenants/globex"],
        "realm_access": {"roles": ["tenant:acme:admin", "tenant:globex:member"]},
    }
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="x",
        backend_client_secret="y",
    )
    services = KeycloakServices(config=cfg, validator=validator, admin=MagicMock())

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(return_value=User(id=7, username="alice", email="alice@acme.test"))

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store
    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)

    app = FastAPI()
    app.include_router(me_router)
    return TestClient(app)


def test_me_returns_principal_and_tenant_list(client):
    r = client.get(
        "/api/me",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@acme.test"
    assert body["active_tenant"] == "acme"
    assert body["active_role"] == "admin"
    assert sorted(t["slug"] for t in body["tenants"]) == ["acme", "globex"]
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/web/test_me_route.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement route**

```python
# atria/web/routes/me.py
from __future__ import annotations

import re
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from atria.models.user import User
from atria.web.dependencies.auth import require_authenticated_user

router = APIRouter(prefix="/api", tags=["me"])

_TENANT_GROUP_RE = re.compile(r"^/tenants/([^/]+)$")


class TenantInfo(BaseModel):
    slug: str


class MeResponse(BaseModel):
    user_id: int
    email: str | None
    username: str
    active_tenant: str
    active_role: str
    is_platform_admin: bool
    tenants: list[TenantInfo]


@router.get("/me", response_model=MeResponse)
async def get_me(request: Request, user: User = Depends(require_authenticated_user)) -> MeResponse:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        # Legacy mode — fabricate a single-tenant response.
        return MeResponse(
            user_id=user.id,
            email=user.email,
            username=user.username,
            active_tenant="default",
            active_role="admin",
            is_platform_admin=True,
            tenants=[TenantInfo(slug="default")],
        )
    tenant_slugs = []
    for g in principal.raw_groups:
        m = _TENANT_GROUP_RE.match(g)
        if m:
            tenant_slugs.append(m.group(1))
    return MeResponse(
        user_id=user.id,
        email=user.email,
        username=principal.username or user.username,
        active_tenant=principal.tenant_id,
        active_role=principal.tenant_role,
        is_platform_admin=principal.is_platform_admin,
        tenants=[TenantInfo(slug=s) for s in tenant_slugs],
    )
```

- [ ] **Step 4: Register the router in `atria/web/server.py`**

Find the section where existing routers are included (look for `include_router`) and add:

```python
from atria.web.routes.me import router as me_router
# ...
app.include_router(me_router)
```

(Note: this `/api/me` is in addition to the existing `/api/auth/me` cookie endpoint — they serve different modes.)

- [ ] **Step 5: Run to pass**

```bash
uv run pytest tests/web/test_me_route.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add atria/web/routes/me.py atria/web/server.py tests/web/test_me_route.py
git commit -m "feat(auth): GET /api/me with tenant list"
```

---

## Task 8: Tenant admin routes

**Files:**
- Create: `atria/web/routes/admin_tenants.py`
- Modify: `atria/web/server.py` (register)
- Create: `tests/web/test_admin_tenants_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_admin_tenants_routes.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.admin_client import TenantSummary
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web import state as state_module
from atria.web.routes.admin_tenants import router as admin_tenants_router


def _setup(monkeypatch, *, roles):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid",
        "email": "admin@platform.test",
        "preferred_username": "admin",
        "groups": [],
        "realm_access": {"roles": roles},
    }
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="x",
        backend_client_secret="y",
    )
    admin = MagicMock()
    admin.list_tenant_groups.return_value = [TenantSummary(id="G1", slug="acme", name="Acme")]
    services = KeycloakServices(config=cfg, validator=validator, admin=admin)

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(return_value=User(id=1, username="admin", email="admin@platform.test"))

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store
    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)

    app = FastAPI()
    app.include_router(admin_tenants_router)
    return TestClient(app), admin


def test_list_tenants_requires_platform_admin(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["tenant:acme:member"])
    r = client.get("/api/admin/tenants", headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"})
    assert r.status_code == 403


def test_list_tenants_ok_for_platform_admin(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["platform:admin"])
    r = client.get("/api/admin/tenants", headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"})
    assert r.status_code == 200
    assert r.json() == [{"id": "G1", "slug": "acme", "name": "Acme"}]


def test_create_tenant_calls_admin_client(monkeypatch):
    client, admin = _setup(monkeypatch, roles=["platform:admin"])
    r = client.post(
        "/api/admin/tenants",
        json={"slug": "globex", "name": "Globex Corp"},
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 201
    admin.create_tenant.assert_called_once()
    spec = admin.create_tenant.call_args.args[0]
    assert spec.slug == "globex"
    assert spec.name == "Globex Corp"


def test_delete_tenant(monkeypatch):
    client, admin = _setup(monkeypatch, roles=["platform:admin"])
    r = client.delete(
        "/api/admin/tenants/globex",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 204
    admin.delete_tenant.assert_called_once_with("globex")
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/web/test_admin_tenants_routes.py -v
```

- [ ] **Step 3: Implement**

```python
# atria/web/routes/admin_tenants.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from atria.core.auth.keycloak.admin_client import TenantSpec, TenantSummary
from atria.core.auth.keycloak.principal import require_role
from atria.models.user import User
from atria.web.dependencies.auth import require_authenticated_user
from atria.web.state import get_state

router = APIRouter(prefix="/api/admin/tenants", tags=["admin-tenants"])


class TenantOut(BaseModel):
    id: str
    slug: str
    name: str


class CreateTenantBody(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=200)


def _admin():
    services = get_state().keycloak
    if services is None:
        from fastapi import HTTPException
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Keycloak not configured")
    return services.admin


@router.get("", response_model=list[TenantOut])
def list_tenants(
    _user: User = Depends(require_authenticated_user),
    _: None = Depends(require_role("platform:admin")),
) -> list[TenantOut]:
    return [TenantOut(id=t.id, slug=t.slug, name=t.name) for t in _admin().list_tenant_groups()]


@router.post("", status_code=201)
def create_tenant(
    body: CreateTenantBody,
    _user: User = Depends(require_authenticated_user),
    _: None = Depends(require_role("platform:admin")),
) -> dict:
    _admin().create_tenant(TenantSpec(slug=body.slug, name=body.name))
    return {"slug": body.slug}


@router.delete("/{slug}", status_code=204)
def delete_tenant(
    slug: str,
    _user: User = Depends(require_authenticated_user),
    _: None = Depends(require_role("platform:admin")),
) -> Response:
    _admin().delete_tenant(slug)
    return Response(status_code=204)
```

- [ ] **Step 4: Register in `server.py`** alongside `me_router`:

```python
from atria.web.routes.admin_tenants import router as admin_tenants_router
app.include_router(admin_tenants_router)
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/web/test_admin_tenants_routes.py -v
```
Expected: 4 passed.

```bash
git add atria/web/routes/admin_tenants.py atria/web/server.py tests/web/test_admin_tenants_routes.py
git commit -m "feat(auth): tenant CRUD admin routes"
```

---

## Task 9: Tenant user management routes

**Files:**
- Create: `atria/web/routes/admin_tenant_users.py`
- Modify: `atria/web/server.py` (register)
- Create: `tests/web/test_admin_tenant_users_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_admin_tenant_users_routes.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.admin_client import TenantUser
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web import state as state_module
from atria.web.routes.admin_tenant_users import router as users_router


def _setup(monkeypatch, *, roles, active_tenant="acme"):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid",
        "email": "alice@acme.test",
        "preferred_username": "alice",
        "groups": [f"/tenants/{active_tenant}"],
        "realm_access": {"roles": roles},
    }
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="x",
        backend_client_secret="y",
    )
    admin = MagicMock()
    admin.list_tenant_users.return_value = [TenantUser(user_id="u1", username="bob", email="bob@a.test", role="member")]
    admin.invite_user.return_value = "u2"
    services = KeycloakServices(config=cfg, validator=validator, admin=admin)

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(return_value=User(id=1, username="alice", email="alice@acme.test"))

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store
    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)

    app = FastAPI()
    app.include_router(users_router)
    return TestClient(app), admin


def test_member_cannot_list_users(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["tenant:acme:member"])
    r = client.get("/api/admin/tenants/acme/users", headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"})
    assert r.status_code == 403


def test_tenant_admin_can_list_users(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["tenant:acme:admin"])
    r = client.get("/api/admin/tenants/acme/users", headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"})
    assert r.status_code == 200
    assert r.json() == [{"user_id": "u1", "username": "bob", "email": "bob@a.test", "role": "member"}]


def test_tenant_admin_for_other_tenant_cannot_access(monkeypatch):
    # Acme admin tries to manage Globex users
    client, _ = _setup(monkeypatch, roles=["tenant:acme:admin"], active_tenant="acme")
    r = client.get(
        "/api/admin/tenants/globex/users",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_platform_admin_can_manage_any_tenant(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["platform:admin"], active_tenant="acme")
    r = client.get(
        "/api/admin/tenants/globex/users",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200


def test_invite_user(monkeypatch):
    client, admin = _setup(monkeypatch, roles=["tenant:acme:admin"])
    r = client.post(
        "/api/admin/tenants/acme/invites",
        json={"email": "carol@a.test", "role": "member"},
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 201
    admin.invite_user.assert_called_once_with("acme", "carol@a.test", "member")


def test_patch_role(monkeypatch):
    client, admin = _setup(monkeypatch, roles=["tenant:acme:admin"])
    r = client.patch(
        "/api/admin/tenants/acme/users/u1",
        json={"role": "admin"},
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 204
    admin.set_user_role.assert_called_once_with("acme", "u1", "admin")


def test_remove_user(monkeypatch):
    client, admin = _setup(monkeypatch, roles=["tenant:acme:admin"])
    r = client.delete(
        "/api/admin/tenants/acme/users/u1",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 204
    admin.remove_user_from_tenant.assert_called_once_with("acme", "u1")
```

- [ ] **Step 2: Run to fail**

```bash
uv run pytest tests/web/test_admin_tenant_users_routes.py -v
```

- [ ] **Step 3: Implement**

```python
# atria/web/routes/admin_tenant_users.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from atria.core.auth.keycloak.principal import CurrentPrincipal
from atria.models.user import User
from atria.web.dependencies.auth import require_authenticated_user
from atria.web.state import get_state

router = APIRouter(prefix="/api/admin/tenants/{slug}/users", tags=["admin-tenant-users"])


class TenantUserOut(BaseModel):
    user_id: str
    username: str
    email: str
    role: str


class InviteBody(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|member)$")


class PatchRoleBody(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


def _admin():
    services = get_state().keycloak
    if services is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Keycloak not configured")
    return services.admin


def _require_tenant_admin(request: Request, slug: str) -> None:
    p: CurrentPrincipal | None = getattr(request.state, "principal", None)
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if p.is_platform_admin:
        return
    if p.tenant_id != slug:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Active tenant does not match URL tenant")
    if p.tenant_role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant admin role required")


@router.get("", response_model=list[TenantUserOut])
def list_users(
    slug: str,
    request: Request,
    _user: User = Depends(require_authenticated_user),
) -> list[TenantUserOut]:
    _require_tenant_admin(request, slug)
    return [
        TenantUserOut(user_id=u.user_id, username=u.username, email=u.email, role=u.role)
        for u in _admin().list_tenant_users(slug)
    ]


@router.post("/../invites", status_code=201, include_in_schema=False)  # placeholder, see below
def _placeholder() -> None:
    raise HTTPException(status.HTTP_410_GONE)


# Real invite endpoint lives at /api/admin/tenants/{slug}/invites — separate router
invites_router = APIRouter(prefix="/api/admin/tenants/{slug}", tags=["admin-tenant-users"])


@invites_router.post("/invites", status_code=201)
def invite_user(
    slug: str,
    body: InviteBody,
    request: Request,
    _user: User = Depends(require_authenticated_user),
) -> dict:
    _require_tenant_admin(request, slug)
    user_id = _admin().invite_user(slug, str(body.email), body.role)
    return {"user_id": user_id}


@router.patch("/{user_id}", status_code=204)
def patch_role(
    slug: str,
    user_id: str,
    body: PatchRoleBody,
    request: Request,
    _user: User = Depends(require_authenticated_user),
) -> Response:
    _require_tenant_admin(request, slug)
    _admin().set_user_role(slug, user_id, body.role)
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
def remove_user(
    slug: str,
    user_id: str,
    request: Request,
    _user: User = Depends(require_authenticated_user),
) -> Response:
    _require_tenant_admin(request, slug)
    _admin().remove_user_from_tenant(slug, user_id)
    return Response(status_code=204)
```

Remove the placeholder before committing — keep two routers (`router` for list/patch/delete, `invites_router` for `/invites`).

```python
# Final, cleaned version of the file:
# - drop the `_placeholder` def and the `@router.post("/../invites", ...)` block
# - export both `router` and `invites_router`
```

- [ ] **Step 4: Register both routers in `server.py`**

```python
from atria.web.routes.admin_tenant_users import router as admin_tenant_users_router, invites_router as admin_tenant_invites_router
app.include_router(admin_tenant_users_router)
app.include_router(admin_tenant_invites_router)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/web/test_admin_tenant_users_routes.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add atria/web/routes/admin_tenant_users.py atria/web/server.py tests/web/test_admin_tenant_users_routes.py
git commit -m "feat(auth): tenant user invite/role/remove routes"
```

---

## Task 10: Realm export file

**Files:**
- Create: `keycloak/realm-export.json`

- [ ] **Step 1: Write `keycloak/realm-export.json`**

```json
{
  "realm": "atria",
  "enabled": true,
  "registrationAllowed": false,
  "loginWithEmailAllowed": true,
  "duplicateEmailsAllowed": false,
  "resetPasswordAllowed": true,
  "editUsernameAllowed": false,
  "verifyEmail": false,
  "accessTokenLifespan": 900,
  "ssoSessionIdleTimeout": 1800,
  "ssoSessionMaxLifespan": 36000,
  "roles": {
    "realm": [
      { "name": "platform:admin", "description": "Platform super-admin" }
    ]
  },
  "groups": [
    { "name": "tenants" }
  ],
  "clients": [
    {
      "clientId": "atria-web",
      "name": "Atria Web SPA",
      "enabled": true,
      "publicClient": true,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": false,
      "redirectUris": ["http://localhost:8080/*"],
      "webOrigins": ["http://localhost:8080"],
      "attributes": { "pkce.code.challenge.method": "S256" },
      "protocolMappers": [
        {
          "name": "groups",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-group-membership-mapper",
          "config": {
            "full.path": "true",
            "id.token.claim": "true",
            "access.token.claim": "true",
            "claim.name": "groups",
            "userinfo.token.claim": "true"
          }
        }
      ]
    },
    {
      "clientId": "atria-backend",
      "name": "Atria Backend Service",
      "enabled": true,
      "publicClient": false,
      "serviceAccountsEnabled": true,
      "directAccessGrantsEnabled": false,
      "standardFlowEnabled": false,
      "secret": "CHANGE-ME-IN-ENV",
      "attributes": {}
    }
  ],
  "users": [
    {
      "username": "platformadmin",
      "email": "admin@atria.local",
      "enabled": true,
      "emailVerified": true,
      "credentials": [{ "type": "password", "value": "admin", "temporary": true }],
      "realmRoles": ["platform:admin"]
    },
    {
      "username": "service-account-atria-backend",
      "enabled": true,
      "serviceAccountClientId": "atria-backend",
      "clientRoles": {
        "realm-management": ["manage-users", "manage-clients", "view-realm", "view-users", "query-users", "query-groups"]
      }
    }
  ]
}
```

(Note: the `secret` value here is bootstrap-only. In `docker-compose.yml` we set the same value via `KEYCLOAK_BACKEND_CLIENT_SECRET`. After first boot, rotate via the admin console.)

- [ ] **Step 2: Commit**

```bash
git add keycloak/realm-export.json
git commit -m "feat(auth): keycloak realm bootstrap export"
```

---

## Task 11: docker-compose changes

**Files:**
- Modify: `schema.sql`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Inspect current `schema.sql`**

```bash
head -5 schema.sql
```

- [ ] **Step 2: Prepend `CREATE DATABASE keycloak;`**

Edit `schema.sql` — the first non-comment line should be:

```sql
CREATE DATABASE keycloak;
```

(Postgres init scripts run only when the data directory is empty, so this is fine on fresh `up`. For existing volumes, document a manual `CREATE DATABASE keycloak;` step.)

- [ ] **Step 3: Add Keycloak service and env to `docker-compose.yml`**

Add after the `adminer` service:

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    restart: unless-stopped
    command: ["start-dev", "--import-realm"]
    environment:
      - KC_DB=postgres
      - KC_DB_URL=jdbc:postgresql://db:5432/keycloak
      - KC_DB_USERNAME=atria
      - KC_DB_PASSWORD=atria
      - KC_HOSTNAME=localhost
      - KC_HTTP_ENABLED=true
      - KEYCLOAK_ADMIN=admin
      - KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD:-admin}
    ports:
      - "8082:8080"
    volumes:
      - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080; printf 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\n\\r\\n' >&3; head -n 1 <&3 | grep -q '200'"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 30s
```

Add to the `atria` service `environment:`:

```yaml
      - AUTH_MODE=${AUTH_MODE:-keycloak}
      - KEYCLOAK_URL=http://keycloak:8080
      - KEYCLOAK_PUBLIC_URL=${KEYCLOAK_PUBLIC_URL:-http://localhost:8082}
      - KEYCLOAK_REALM=atria
      - KEYCLOAK_BACKEND_CLIENT_ID=atria-backend
      - KEYCLOAK_BACKEND_CLIENT_SECRET=${KEYCLOAK_BACKEND_CLIENT_SECRET:-CHANGE-ME-IN-ENV}
```

Add to the `atria` `depends_on:`:

```yaml
      keycloak:
        condition: service_healthy
```

- [ ] **Step 4: Smoke-test the stack**

```bash
docker compose down -v   # destroys volumes — only if you don't care about local data
docker compose up -d db
sleep 10
docker compose up -d keycloak
docker compose logs -f keycloak | head -100   # confirm realm import succeeded
docker compose up -d atria adminer
docker compose ps
```

Expected: all services `healthy`. Visit `http://localhost:8082` and log in as `admin/admin`.

- [ ] **Step 5: Commit**

```bash
git add schema.sql docker-compose.yml
git commit -m "feat(auth): add Keycloak service to docker-compose"
```

---

## Task 12: Integration test against a real Keycloak

**Files:**
- Create: `tests/integration/__init__.py` (if missing)
- Create: `tests/integration/test_auth_keycloak.py`
- Modify: `tests/conftest.py` (add a marker, optional)

- [ ] **Step 1: Confirm `tests/integration/` exists or create it**

```bash
ls tests/integration/ || mkdir tests/integration && touch tests/integration/__init__.py
```

- [ ] **Step 2: Write the integration test**

```python
# tests/integration/test_auth_keycloak.py
"""Integration test against a live Keycloak.

Skipped unless ATRIA_KEYCLOAK_INTEGRATION=1 is set and `docker compose up -d keycloak` is running.
"""
from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("ATRIA_KEYCLOAK_INTEGRATION") != "1",
    reason="set ATRIA_KEYCLOAK_INTEGRATION=1 and run docker compose first",
)


KC_BASE = os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082")
REALM = "atria"


def _get_password_token(username: str, password: str, client_id: str = "atria-web") -> str:
    # Enable directAccessGrants temporarily on atria-web in the admin console
    # to make this work, OR use a dedicated test client.
    resp = httpx.post(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def test_platform_admin_can_create_tenant_via_api(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("KEYCLOAK_URL", os.getenv("KEYCLOAK_INTERNAL_URL", KC_BASE))
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", KC_BASE)
    monkeypatch.setenv("KEYCLOAK_REALM", REALM)
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend")
    monkeypatch.setenv(
        "KEYCLOAK_BACKEND_CLIENT_SECRET",
        os.environ["KEYCLOAK_BACKEND_CLIENT_SECRET"],
    )

    from atria.web.server import build_app  # adjust if the app factory is named differently

    token = _get_password_token("platformadmin", "admin")
    app = build_app()
    client = TestClient(app)
    r = client.post(
        "/api/admin/tenants",
        json={"slug": "inttest", "name": "Integration Test"},
        headers={"Authorization": f"Bearer {token}", "X-Atria-Tenant": "inttest"},
    )
    assert r.status_code == 201

    # Cleanup
    r = client.delete(
        "/api/admin/tenants/inttest",
        headers={"Authorization": f"Bearer {token}", "X-Atria-Tenant": "inttest"},
    )
    assert r.status_code == 204
```

- [ ] **Step 3: Run (manually, when stack is up)**

```bash
docker compose up -d
ATRIA_KEYCLOAK_INTEGRATION=1 KEYCLOAK_BACKEND_CLIENT_SECRET=CHANGE-ME-IN-ENV uv run pytest tests/integration/test_auth_keycloak.py -v
```

(If the app factory is named differently, fix the import.)

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_auth_keycloak.py tests/integration/__init__.py
git commit -m "test(auth): integration test against live Keycloak"
```

---

## Task 13: Frontend — install OIDC client and auth provider

**Files:**
- Modify: `web-ui/package.json`
- Create: `web-ui/src/auth/oidc.ts`
- Create: `web-ui/src/auth/AuthProvider.tsx`
- Create: `web-ui/src/stores/tenantStore.ts`
- Create: `web-ui/src/auth/apiClient.ts`
- Modify: `web-ui/src/App.tsx`

- [ ] **Step 1: Install `oidc-client-ts`**

```bash
cd web-ui && npm install oidc-client-ts
```

- [ ] **Step 2: Create `web-ui/src/auth/oidc.ts`**

```ts
// web-ui/src/auth/oidc.ts
import { UserManager, WebStorageStateStore, User } from "oidc-client-ts";

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8082";
const REALM = import.meta.env.VITE_KEYCLOAK_REALM ?? "atria";
const CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "atria-web";

export const userManager = new UserManager({
  authority: `${KEYCLOAK_URL}/realms/${REALM}`,
  client_id: CLIENT_ID,
  redirect_uri: `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: "code",
  scope: "openid profile email",
  userStore: new WebStorageStateStore({ store: window.localStorage }),
  automaticSilentRenew: true,
});

export async function login() {
  await userManager.signinRedirect();
}

export async function logout() {
  await userManager.signoutRedirect();
}

export async function getCurrentUser(): Promise<User | null> {
  return userManager.getUser();
}
```

- [ ] **Step 3: Create `web-ui/src/stores/tenantStore.ts`**

```ts
// web-ui/src/stores/tenantStore.ts
import { create } from "zustand";

type Tenant = { slug: string };

type TenantState = {
  active: string | null;
  tenants: Tenant[];
  setActive: (slug: string) => void;
  setTenants: (tenants: Tenant[]) => void;
};

const STORAGE_KEY = "atria.activeTenant";

export const useTenantStore = create<TenantState>((set) => ({
  active: localStorage.getItem(STORAGE_KEY),
  tenants: [],
  setActive: (slug) => {
    localStorage.setItem(STORAGE_KEY, slug);
    set({ active: slug });
  },
  setTenants: (tenants) => set({ tenants }),
}));
```

- [ ] **Step 4: Create `web-ui/src/auth/apiClient.ts`**

```ts
// web-ui/src/auth/apiClient.ts
import { userManager } from "./oidc";
import { useTenantStore } from "@/stores/tenantStore";

export async function apiFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const user = await userManager.getUser();
  const headers = new Headers(init.headers ?? {});
  if (user?.access_token) {
    headers.set("Authorization", `Bearer ${user.access_token}`);
  }
  const tenant = useTenantStore.getState().active;
  if (tenant) headers.set("X-Atria-Tenant", tenant);
  return fetch(input, { ...init, headers });
}
```

- [ ] **Step 5: Create `web-ui/src/auth/AuthProvider.tsx`**

```tsx
// web-ui/src/auth/AuthProvider.tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { User } from "oidc-client-ts";
import { userManager, login } from "./oidc";
import { useTenantStore } from "@/stores/tenantStore";
import { apiFetch } from "./apiClient";

type Me = {
  user_id: number;
  email: string | null;
  username: string;
  active_tenant: string;
  active_role: string;
  is_platform_admin: boolean;
  tenants: { slug: string }[];
};

type AuthCtx = {
  user: User | null;
  me: Me | null;
  loading: boolean;
};

const Ctx = createContext<AuthCtx>({ user: null, me: null, loading: true });
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const setTenants = useTenantStore((s) => s.setTenants);
  const setActive = useTenantStore((s) => s.setActive);
  const active = useTenantStore((s) => s.active);

  useEffect(() => {
    async function init() {
      // Handle the callback URL
      if (window.location.pathname === "/auth/callback") {
        await userManager.signinRedirectCallback();
        window.history.replaceState({}, "", "/");
      }
      const u = await userManager.getUser();
      if (!u || u.expired) {
        await login();
        return;
      }
      setUser(u);

      // Bootstrap tenant selection. /api/me needs X-Atria-Tenant — pick any group claim.
      let tenant = active;
      if (!tenant) {
        const groups: string[] = (u.profile as any).groups ?? [];
        const slugs = groups
          .map((g) => g.match(/^\/tenants\/([^/]+)$/)?.[1])
          .filter((s): s is string => !!s);
        if (slugs.length) {
          setActive(slugs[0]);
          tenant = slugs[0];
        }
      }
      if (tenant) {
        const r = await apiFetch("/api/me");
        if (r.ok) {
          const body = (await r.json()) as Me;
          setMe(body);
          setTenants(body.tenants);
        }
      }
      setLoading(false);
    }
    init();
  }, []);

  return <Ctx.Provider value={{ user, me, loading }}>{children}</Ctx.Provider>;
}
```

- [ ] **Step 6: Wrap the app in `AuthProvider`**

Edit `web-ui/src/App.tsx` — wrap the existing tree:

```tsx
import { AuthProvider } from "@/auth/AuthProvider";
// ...
<AuthProvider>
  {/* existing app tree */}
</AuthProvider>
```

- [ ] **Step 7: Commit**

```bash
git add web-ui/package.json web-ui/package-lock.json web-ui/src/auth web-ui/src/stores/tenantStore.ts web-ui/src/App.tsx
git commit -m "feat(auth): web-ui OIDC client, tenant store, AuthProvider"
```

---

## Task 14: TenantSwitcher component

**Files:**
- Create: `web-ui/src/components/TenantSwitcher.tsx`
- Modify: the layout header to include it (likely `web-ui/src/components/Layout/Header.tsx` or wherever the top bar lives)

- [ ] **Step 1: Locate the header**

```bash
grep -rln "Layout" web-ui/src/components/Layout | head
```

- [ ] **Step 2: Create the component**

```tsx
// web-ui/src/components/TenantSwitcher.tsx
import { useAuth } from "@/auth/AuthProvider";
import { useTenantStore } from "@/stores/tenantStore";

export function TenantSwitcher() {
  const { me } = useAuth();
  const active = useTenantStore((s) => s.active);
  const setActive = useTenantStore((s) => s.setActive);
  if (!me || me.tenants.length === 0) return null;

  return (
    <select
      value={active ?? ""}
      onChange={(e) => {
        setActive(e.target.value);
        window.location.reload(); // simplest way to re-resolve principal/tenant scope
      }}
      className="text-sm border rounded px-2 py-1"
    >
      {me.tenants.map((t) => (
        <option key={t.slug} value={t.slug}>
          {t.slug}
        </option>
      ))}
    </select>
  );
}
```

- [ ] **Step 3: Add `<TenantSwitcher />` to the layout header JSX** (next to user/profile area).

- [ ] **Step 4: Smoke-test in the browser**

```bash
make build-ui && make run
```
Log in as `platformadmin / admin`, complete the password change. Confirm the switcher renders when you have tenants and `/api/me` returns them.

- [ ] **Step 5: Commit**

```bash
git add web-ui/src/components/TenantSwitcher.tsx web-ui/src/components/Layout/
git commit -m "feat(auth): tenant switcher in app header"
```

---

## Task 15: Admin UI — Tenants page

**Files:**
- Create: `web-ui/src/pages/admin/TenantsPage.tsx`
- Modify: `web-ui/src/App.tsx` (add route)

- [ ] **Step 1: Implement page**

```tsx
// web-ui/src/pages/admin/TenantsPage.tsx
import { useEffect, useState } from "react";
import { apiFetch } from "@/auth/apiClient";
import { useAuth } from "@/auth/AuthProvider";

type Tenant = { id: string; slug: string; name: string };

export function TenantsPage() {
  const { me } = useAuth();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const r = await apiFetch("/api/admin/tenants");
    if (r.ok) setTenants(await r.json());
  }
  useEffect(() => {
    load();
  }, []);

  if (!me?.is_platform_admin) {
    return <div className="p-4">Platform admin access required.</div>;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const r = await apiFetch("/api/admin/tenants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, name }),
    });
    if (!r.ok) {
      setErr(await r.text());
      return;
    }
    setSlug("");
    setName("");
    load();
  }

  async function remove(s: string) {
    if (!confirm(`Delete tenant ${s}?`)) return;
    const r = await apiFetch(`/api/admin/tenants/${s}`, { method: "DELETE" });
    if (!r.ok) setErr(await r.text());
    load();
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold mb-4">Tenants</h1>
      <form onSubmit={create} className="flex gap-2 mb-4">
        <input
          className="border rounded px-2 py-1"
          placeholder="slug (lowercase)"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <input
          className="border rounded px-2 py-1 flex-1"
          placeholder="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="border rounded px-3 py-1">
          Create
        </button>
      </form>
      {err && <div className="text-red-600 mb-3">{err}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b">
            <th>Slug</th>
            <th>Name</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {tenants.map((t) => (
            <tr key={t.id} className="border-b">
              <td>{t.slug}</td>
              <td>{t.name}</td>
              <td className="text-right">
                <button onClick={() => remove(t.slug)} className="text-red-600">
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Wire route** in `App.tsx` (router section):

```tsx
import { TenantsPage } from "@/pages/admin/TenantsPage";
// in the router:
<Route path="/admin/tenants" element={<TenantsPage />} />
```

- [ ] **Step 3: Smoke-test** — log in as platform admin, navigate to `/admin/tenants`, create a tenant, verify it shows in the list and in the Keycloak admin console under `/tenants/<slug>`. Delete it.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/pages/admin/TenantsPage.tsx web-ui/src/App.tsx
git commit -m "feat(auth): admin tenants page"
```

---

## Task 16: Admin UI — Tenant users page

**Files:**
- Create: `web-ui/src/pages/admin/TenantUsersPage.tsx`
- Modify: `web-ui/src/App.tsx` (add route)

- [ ] **Step 1: Implement**

```tsx
// web-ui/src/pages/admin/TenantUsersPage.tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiFetch } from "@/auth/apiClient";
import { useAuth } from "@/auth/AuthProvider";

type TenantUser = { user_id: string; username: string; email: string; role: string };

export function TenantUsersPage() {
  const { slug = "" } = useParams();
  const { me } = useAuth();
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const r = await apiFetch(`/api/admin/tenants/${slug}/users`);
    if (r.ok) setUsers(await r.json());
    else setErr(await r.text());
  }
  useEffect(() => {
    load();
  }, [slug]);

  const canAdmin = me?.is_platform_admin || (me?.active_tenant === slug && me?.active_role === "admin");
  if (!canAdmin) return <div className="p-4">Tenant admin access required.</div>;

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    const r = await apiFetch(`/api/admin/tenants/${slug}/invites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
    });
    if (!r.ok) {
      setErr(await r.text());
      return;
    }
    setInviteEmail("");
    load();
  }

  async function changeRole(user_id: string, role: "admin" | "member") {
    const r = await apiFetch(`/api/admin/tenants/${slug}/users/${user_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!r.ok) setErr(await r.text());
    load();
  }

  async function remove(user_id: string) {
    if (!confirm("Remove user from tenant?")) return;
    const r = await apiFetch(`/api/admin/tenants/${slug}/users/${user_id}`, { method: "DELETE" });
    if (!r.ok) setErr(await r.text());
    load();
  }

  return (
    <div className="p-6 max-w-3xl">
      <h1 className="text-xl font-semibold mb-4">{slug} — users</h1>
      <form onSubmit={invite} className="flex gap-2 mb-4">
        <input
          className="border rounded px-2 py-1 flex-1"
          placeholder="email@example.com"
          value={inviteEmail}
          onChange={(e) => setInviteEmail(e.target.value)}
        />
        <select
          className="border rounded px-2 py-1"
          value={inviteRole}
          onChange={(e) => setInviteRole(e.target.value as "admin" | "member")}
        >
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
        <button type="submit" className="border rounded px-3 py-1">
          Invite
        </button>
      </form>
      {err && <div className="text-red-600 mb-3">{err}</div>}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b">
            <th>User</th>
            <th>Email</th>
            <th>Role</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.user_id} className="border-b">
              <td>{u.username}</td>
              <td>{u.email}</td>
              <td>
                <select
                  value={u.role}
                  onChange={(e) => changeRole(u.user_id, e.target.value as "admin" | "member")}
                >
                  <option value="member">member</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td className="text-right">
                <button onClick={() => remove(u.user_id)} className="text-red-600">
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Add route** in `App.tsx`:

```tsx
import { TenantUsersPage } from "@/pages/admin/TenantUsersPage";
<Route path="/admin/tenants/:slug/users" element={<TenantUsersPage />} />
```

- [ ] **Step 3: Smoke-test** end-to-end: create a tenant, invite a user (use a real email or check Keycloak's email logs), confirm they appear; change role; remove them.

- [ ] **Step 4: Commit**

```bash
git add web-ui/src/pages/admin/TenantUsersPage.tsx web-ui/src/App.tsx
git commit -m "feat(auth): admin tenant users page"
```

---

## Task 17: Full-stack smoke + cross-tenant 403 check

This is the E2E check per `CLAUDE.md`. It is manual; no test file.

- [ ] **Step 1: Reset stack**

```bash
docker compose down -v
docker compose up -d
```

- [ ] **Step 2: Set the backend client secret**

In Keycloak admin (`http://localhost:8082`, admin/admin), open client `atria-backend` → Credentials → copy the secret. Put it in `.env` as `KEYCLOAK_BACKEND_CLIENT_SECRET=...`. Restart `atria`:

```bash
docker compose up -d --no-deps atria
```

- [ ] **Step 3: Build UI and serve**

```bash
make build-ui
```

Browse to `http://localhost:8080`. You should be redirected to Keycloak. Log in as `platformadmin / admin`, set a new password.

- [ ] **Step 4: Exercise the golden path**

1. Go to `/admin/tenants`, create `acme` and `globex`.
2. Switch active tenant to `acme` (header switcher).
3. Go to `/admin/tenants/acme/users`, invite `bob@example.test` as admin.
4. Verify the invite email logs (or in dev, use Keycloak's "Required user actions" link to set the password manually).
5. Log out, log in as `bob`. Confirm Bob sees only `acme` in his tenant switcher.
6. As Bob, attempt `curl -H "Authorization: Bearer $BOB" -H "X-Atria-Tenant: globex" http://localhost:8080/api/me` → expect 403.

- [ ] **Step 5: Document any deviations** in the spec's "Open Follow-Ups" section as needed.

- [ ] **Step 6: Final lint + tests**

```bash
make check
make test
```

- [ ] **Step 7: Commit any documentation/tweaks**

```bash
git add -A
git commit -m "chore(auth): post-smoke cleanups" || true
```

---

## Self-Review Notes

- **Spec coverage:** Architecture (Task 1–6), token shape + tenant resolution (Tasks 3–4), Admin API surface (Tasks 5, 8, 9), Admin UI (Tasks 13–16), Docker Compose + realm export (Tasks 10–11), testing (Tasks 1–9 unit + 12 integration + 17 E2E), rollout via `AUTH_MODE` (Tasks 1, 6). All requirement bullets in the spec are mapped.
- **Placeholders:** the file `admin_tenant_users.py` initially shows a `_placeholder` block then asks the engineer to remove it before commit. This is a real cleanup instruction, not a code placeholder — it's there because we have two routers (one prefixed with `{slug}/users`, the other with `{slug}`) and the engineer needs to understand why.
- **Type consistency:** `CurrentPrincipal` shape, `tenant:<slug>:<role>` role format, and the `/tenants/<slug>` group path are used consistently across tasks. `KeycloakAdminClient` method names match between Task 5 (definition), Task 8 (`create_tenant`, `delete_tenant`, `list_tenant_groups`), and Task 9 (`list_tenant_users`, `invite_user`, `set_user_role`, `remove_user_from_tenant`).
- **Out of scope (explicit in spec):** No `tenant_id` column sweep of Atria's data models; production TLS; per-tenant IdPs.
