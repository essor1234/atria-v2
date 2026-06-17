from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from atria.core.auth.keycloak.admin_client import TenantSpec
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
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Keycloak not configured"
        )
    return services.admin


@router.get("", response_model=list[TenantOut])
def list_tenants(
    _user: User = Depends(require_authenticated_user),
    _: None = Depends(require_role("platform:admin")),
) -> list[TenantOut]:
    return [
        TenantOut(id=t.id, slug=t.slug, name=t.name)
        for t in _admin().list_tenant_groups()
    ]


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
