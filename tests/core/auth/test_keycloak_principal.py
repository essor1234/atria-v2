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
