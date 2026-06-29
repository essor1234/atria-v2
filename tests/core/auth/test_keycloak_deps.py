from unittest.mock import MagicMock

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import InvalidTokenError
from atria.core.auth.keycloak.principal import (
    CurrentPrincipal,
    get_current_principal_factory,
    require_role,
)


def _cfg():
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
    )


def _claims(groups, roles):
    return {
        "sub": "user-uuid",
        "email": "a@b.c",
        "preferred_username": "alice",
        "groups": groups,
        "realm_access": {"roles": roles},
    }


def _make_app(validator):
    cfg = _cfg()
    dep = get_current_principal_factory(cfg, validator)
    app = FastAPI()

    @app.get("/whoami")
    def whoami(p: CurrentPrincipal = Depends(dep)):
        return {"user": p.user_id, "tenant": p.tenant_id, "role": p.tenant_role}

    @app.get("/admin-only")
    def admin_only(
        p: CurrentPrincipal = Depends(dep),
        _: None = Depends(require_role("platform:admin")),
    ):
        return {"ok": True}

    return app


def test_401_without_bearer():
    validator = MagicMock()
    client = TestClient(_make_app(validator))
    r = client.get("/whoami", headers={"X-Atria-Tenant": "acme"})
    assert r.status_code == 401


def test_403_when_user_not_in_tenant():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/other"], ["tenant:other:admin"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_200_when_member():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200
    assert r.json() == {"user": "user-uuid", "tenant": "acme", "role": "member"}


def test_401_when_token_invalid():
    validator = MagicMock()
    validator.validate.side_effect = InvalidTokenError("bad sig")
    client = TestClient(_make_app(validator))
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 401


def test_require_role_platform_admin_blocks_member():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/admin-only",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 403


def test_require_role_platform_admin_allows_admin():
    validator = MagicMock()
    validator.validate.return_value = _claims([], ["platform:admin"])
    client = TestClient(_make_app(validator))
    r = client.get(
        "/admin-only",
        headers={"Authorization": "Bearer x", "X-Atria-Tenant": "acme"},
    )
    assert r.status_code == 200


def test_missing_tenant_header_returns_400():
    validator = MagicMock()
    validator.validate.return_value = _claims(["/tenants/acme"], ["tenant:acme:member"])
    client = TestClient(_make_app(validator))
    r = client.get("/whoami", headers={"Authorization": "Bearer x"})
    assert r.status_code == 400
