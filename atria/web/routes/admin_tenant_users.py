from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from atria.core.auth.keycloak.principal import CurrentPrincipal
from atria.models.user import User
from atria.web.dependencies.auth import require_authenticated_user
from atria.web.state import get_state

router = APIRouter(prefix="/api/admin/tenants/{slug}/users", tags=["admin-tenant-users"])
invites_router = APIRouter(prefix="/api/admin/tenants/{slug}", tags=["admin-tenant-users"])


class TenantUserOut(BaseModel):
    user_id: str
    username: str
    email: str
    role: str


class InviteBody(BaseModel):
    email: str = Field(min_length=3, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
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
