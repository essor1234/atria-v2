from unittest.mock import AsyncMock, MagicMock

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
    from atria.web.dependencies import auth as auth_dep_module
    from atria.web.routes import admin_tenants as admin_tenants_module
    monkeypatch.setattr(auth_dep_module, "get_state", lambda: fake_state)
    monkeypatch.setattr(admin_tenants_module, "get_state", lambda: fake_state)

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
