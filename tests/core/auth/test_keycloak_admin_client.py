
import httpx

from atria.core.auth.keycloak.admin_client import KeycloakAdminClient, TenantSpec
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig


def _cfg():
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://kc",
        public_url="http://kc",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
    )


def _mock_transport(routes):
    """routes: list of (method, url_predicate, response_factory)."""
    def handler(request: httpx.Request) -> httpx.Response:
        for method, pred, factory in routes:
            if request.method == method and pred(request.url.path):
                return factory(request)
        return httpx.Response(404, json={"path": request.url.path})
    return httpx.MockTransport(handler)


def test_acquires_service_account_token_lazily():
    calls = {"token": 0, "groups": 0}

    def token_response(req):
        calls["token"] += 1
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def groups_response(req):
        calls["groups"] += 1
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json=[])

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token_response),
        ("GET", lambda p: p.endswith("/groups"), groups_response),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.list_tenant_groups()
    client.list_tenant_groups()
    assert calls["token"] == 1  # token cached
    assert calls["groups"] == 2


def test_create_tenant_creates_group_and_roles():
    seen = []

    def token(req):
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def get_groups(req):
        # Return the parent /tenants group so create_tenant can find it.
        return httpx.Response(200, json=[{"id": "PARENT", "name": "tenants", "path": "/tenants"}])

    def post_children(req):
        seen.append(("group", req.read().decode()))
        return httpx.Response(201, headers={"Location": "http://kc/admin/realms/atria/groups/G1"})

    def post_roles(req):
        seen.append(("role", req.read().decode()))
        return httpx.Response(201)

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token),
        ("GET", lambda p: p.endswith("/groups"), get_groups),
        ("POST", lambda p: p.endswith("/children"), post_children),
        ("POST", lambda p: p.endswith("/roles"), post_roles),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.create_tenant(TenantSpec(slug="acme", name="Acme Inc"))
    kinds = [k for k, _ in seen]
    assert kinds == ["group", "role", "role"]


def test_delete_tenant_deletes_group_and_roles():
    def token(req):
        return httpx.Response(200, json={"access_token": "AT", "expires_in": 60})

    def get_group_by_path(req):
        # Path: /groups?search=acme — return the group id
        return httpx.Response(200, json=[{"id": "G1", "name": "acme", "path": "/tenants/acme"}])

    deleted = []

    def delete_group(req):
        deleted.append(("group", req.url.path))
        return httpx.Response(204)

    def delete_role(req):
        deleted.append(("role", req.url.path))
        return httpx.Response(204)

    transport = _mock_transport([
        ("POST", lambda p: p.endswith("/protocol/openid-connect/token"), token),
        ("GET", lambda p: p.endswith("/groups"), get_group_by_path),
        ("DELETE", lambda p: "/groups/G1" in p, delete_group),
        ("DELETE", lambda p: "/roles/tenant:acme:" in p, delete_role),
    ])

    client = KeycloakAdminClient(_cfg(), transport=transport)
    client.delete_tenant("acme")
    kinds = [k for k, _ in deleted]
    assert kinds.count("role") == 2
    assert kinds.count("group") == 1
