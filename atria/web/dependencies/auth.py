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
        username = principal.username or (
            principal.email.split("@")[0] if principal.email else principal.user_id[:8]
        )
        user = await user_store.create_user(
            username=username, password_hash="", email=principal.email
        )

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
