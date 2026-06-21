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


# --- FastAPI integration ---------------------------------------------------

from fastapi import HTTPException, Request, status  # noqa: E402
from typing import Callable  # noqa: E402

from atria.core.auth.keycloak.config import KeycloakConfig  # noqa: E402
from atria.core.auth.keycloak.jwt import InvalidTokenError, TokenValidator  # noqa: E402


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
