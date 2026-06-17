from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web import state as state_module
from atria.web.routes.me import router as me_router


@pytest.fixture
def client(monkeypatch):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid",
        "email": "alice@acme.test",
        "preferred_username": "alice",
        "groups": ["/tenants/acme", "/tenants/globex"],
        "realm_access": {"roles": ["tenant:acme:admin", "tenant:globex:member"]},
    }
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="x",
        backend_client_secret="y",
    )
    services = KeycloakServices(config=cfg, validator=validator, admin=MagicMock())

    user_store = MagicMock()
    user_store.get_by_email = AsyncMock(return_value=User(id=7, username="alice", email="alice@acme.test"))

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store
    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)
    from atria.web.dependencies import auth as auth_dep_module
    monkeypatch.setattr(auth_dep_module, "get_state", lambda: fake_state)

    app = FastAPI()
    app.include_router(me_router)
    return TestClient(app)


def test_me_returns_principal_and_tenant_list(client):
    r = client.get(
        "/api/me",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@acme.test"
    assert body["active_tenant"] == "acme"
    assert body["active_role"] == "admin"
    assert sorted(t["slug"] for t in body["tenants"]) == ["acme", "globex"]
