
import pytest

from atria.core.auth.keycloak.config import KeycloakConfig, AuthMode


def test_defaults_to_auth_mode_none(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    cfg = KeycloakConfig.from_env()
    assert cfg.auth_mode is AuthMode.NONE


def test_loads_keycloak_settings(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak:8080")
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082")
    monkeypatch.setenv("KEYCLOAK_REALM", "atria")
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend")
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_SECRET", "shh")
    cfg = KeycloakConfig.from_env()
    assert cfg.auth_mode is AuthMode.KEYCLOAK
    assert cfg.realm == "atria"
    assert cfg.issuer == "http://localhost:8082/realms/atria"
    assert cfg.jwks_url == "http://keycloak:8080/realms/atria/protocol/openid-connect/certs"
    assert cfg.token_url == "http://keycloak:8080/realms/atria/protocol/openid-connect/token"
    assert cfg.admin_base_url == "http://keycloak:8080/admin/realms/atria"
    assert cfg.backend_client_id == "atria-backend"
    assert cfg.backend_client_secret == "shh"


def test_keycloak_mode_requires_secret(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.delenv("KEYCLOAK_BACKEND_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="KEYCLOAK_BACKEND_CLIENT_SECRET"):
        KeycloakConfig.from_env()
