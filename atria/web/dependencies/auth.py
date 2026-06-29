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


async def _resolve_via_bearer(request: Request) -> User:
    state = get_state()
    services = state.keycloak
    assert services is not None

    auth = request.headers.get("Authorization", "")
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

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

    user_store = state.user_store
    user = await user_store.get_by_email(principal.email) if principal.email else None
    if not user:
        username = principal.username or (
            principal.email.split("@")[0] if principal.email else principal.user_id[:8]
        )
        user = await user_store.create_user(
            username=username, password_hash="", email=principal.email
        )

    request.state.principal = principal
    request.state.user = user
    return user


async def _resolve_via_session_cookie(request: Request, token: str) -> User | None:
    """Decode atria_session cookie and look up the user. Returns None on failure."""
    try:
        user_id_str = verify_token(token)
    except Exception:
        return None
    state = get_state()
    user = await state.user_store.get_by_id(int(user_id_str))
    if not user:
        return None
    request.state.user = user
    return user


async def require_authenticated_user(request: Request) -> User:
    """Resolve a user via session cookie (preferred), Keycloak bearer token, or anonymous fallback."""

    state = get_state()
    keycloak_enabled = getattr(state, "keycloak", None) is not None

    # 1. Session cookie path (works in both modes — it's what the Keycloak callback sets).
    session_token = request.cookies.get(TOKEN_COOKIE)
    if session_token:
        user = await _resolve_via_session_cookie(request, session_token)
        if user is not None:
            return user
        if keycloak_enabled:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session cookie")
        # Legacy mode: fall through to anonymous.

    # 2. Bearer token path (API clients in keycloak mode).
    if keycloak_enabled:
        if request.headers.get("Authorization", "").lower().startswith("bearer "):
            return await _resolve_via_bearer(request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    # 3. Legacy anonymous fallback.
    user = _get_anonymous_user()
    request.state.user = user
    return user
