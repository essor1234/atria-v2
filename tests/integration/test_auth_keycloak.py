"""Integration test against a live Keycloak.

Skipped unless ATRIA_KEYCLOAK_INTEGRATION=1 is set and `docker compose up -d keycloak` is running.
"""
from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("ATRIA_KEYCLOAK_INTEGRATION") != "1",
    reason="set ATRIA_KEYCLOAK_INTEGRATION=1 and run docker compose first",
)


KC_BASE = os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082")
REALM = "atria"


def _get_password_token(username: str, password: str, client_id: str = "atria-web") -> str:
    # Enable directAccessGrants temporarily on atria-web in the admin console
    # to make this work, OR use a dedicated test client.
    resp = httpx.post(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def test_platform_admin_can_create_tenant_via_api(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "keycloak")
    monkeypatch.setenv("KEYCLOAK_URL", os.getenv("KEYCLOAK_INTERNAL_URL", KC_BASE))
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", KC_BASE)
    monkeypatch.setenv("KEYCLOAK_REALM", REALM)
    monkeypatch.setenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend")
    monkeypatch.setenv(
        "KEYCLOAK_BACKEND_CLIENT_SECRET",
        os.environ["KEYCLOAK_BACKEND_CLIENT_SECRET"],
    )

    from atria.web.server import build_app  # adjust if the app factory is named differently

    token = _get_password_token("platformadmin", "admin")
    app = build_app()
    client = TestClient(app)
    r = client.post(
        "/api/admin/tenants",
        json={"slug": "inttest", "name": "Integration Test"},
        headers={"Authorization": f"Bearer {token}", "X-Atria-Tenant": "inttest"},
    )
    assert r.status_code == 201

    # Cleanup
    r = client.delete(
        "/api/admin/tenants/inttest",
        headers={"Authorization": f"Bearer {token}", "X-Atria-Tenant": "inttest"},
    )
    assert r.status_code == 204
