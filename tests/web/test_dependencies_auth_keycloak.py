from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.services import KeycloakServices
from atria.models.user import User
from atria.web.dependencies import auth as auth_module
from atria.web.dependencies.auth import require_authenticated_user
from atria.web import state as state_module


@pytest.fixture
def app_with_keycloak(monkeypatch):
    validator = MagicMock()
    validator.validate.return_value = {
        "sub": "kc-uuid-1",
        "email": "alice@acme.test",
        "preferred_username": "alice",
        "groups": ["/tenants/acme"],
        "realm_access": {"roles": ["tenant:acme:member"]},
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
    user_store.get_by_email = AsyncMock(return_value=None)
    user_store.create_user = AsyncMock(
        return_value=User(id=42, username="alice", email="alice@acme.test")
    )

    fake_state = MagicMock()
    fake_state.keycloak = services
    fake_state.user_store = user_store

    monkeypatch.setattr(state_module, "get_state", lambda: fake_state)
    monkeypatch.setattr(auth_module, "get_state", lambda: fake_state)

    app = FastAPI()

    @app.get("/probe")
    async def probe(user: User = Depends(require_authenticated_user)):
        return {"id": user.id, "email": user.email}

    return app, user_store


def test_keycloak_mode_lazy_creates_user(app_with_keycloak):
    app, store = app_with_keycloak
    client = TestClient(app)
    r = client.get(
        "/probe",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"id": 42, "email": "alice@acme.test"}
    store.create_user.assert_awaited_once()


def test_keycloak_mode_missing_bearer_returns_401(app_with_keycloak):
    app, _ = app_with_keycloak
    client = TestClient(app)
    r = client.get("/probe", headers={"X-Atria-Tenant": "acme"})
    assert r.status_code == 401
