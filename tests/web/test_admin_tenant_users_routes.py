from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.admin_client import TenantUser
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web import state as state_module
from atria.web.routes.admin_tenant_users import (
    invites_router,
    router as users_router,
)


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
    admin.list_tenant_users.return_value = [
        TenantUser(user_id="u1", username="bob", email="bob@a.test", role="member")
    ]
    admin.invite_user.return_value = "u2"
    services = KeycloakServices(config=cfg, validator=validator, admin=admin)

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(
        return_value=User(id=1, username="alice", email="alice@acme.test")
    )

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store
    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)
    from atria.web.dependencies import auth as auth_dep_module
    from atria.web.routes import admin_tenant_users as admin_tenant_users_module
    monkeypatch.setattr(auth_dep_module, "get_state", lambda: fake_state)
    monkeypatch.setattr(admin_tenant_users_module, "get_state", lambda: fake_state)

    app = FastAPI()
    app.include_router(users_router)
    app.include_router(invites_router)
    return TestClient(app), admin


def test_member_cannot_list_users(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["tenant:acme:member"])
    r = client.get(
        "/api/admin/tenants/acme/users",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_tenant_admin_can_list_users(monkeypatch):
    client, _ = _setup(monkeypatch, roles=["tenant:acme:admin"])
    r = client.get(
        "/api/admin/tenants/acme/users",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == [
        {"user_id": "u1", "username": "bob", "email": "bob@a.test", "role": "member"}
    ]


def test_tenant_admin_for_other_tenant_cannot_access(monkeypatch):
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
