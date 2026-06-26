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
