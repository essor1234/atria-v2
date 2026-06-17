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
