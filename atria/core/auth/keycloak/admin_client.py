from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx

from atria.core.auth.keycloak.config import KeycloakConfig


@dataclass(frozen=True)
class TenantSpec:
    slug: str
    name: str


@dataclass(frozen=True)
class TenantSummary:
    id: str
    slug: str
    name: str


@dataclass(frozen=True)
class TenantUser:
    user_id: str
    username: str
    email: str
    role: str  # "admin" or "member"


class KeycloakAdminClient:
    """Thin sync wrapper around the Keycloak Admin REST API.

    The service account token is cached until ~30s before expiry.
    Uses sync httpx to keep call sites simple; admin operations are infrequent.
    """

    def __init__(
        self, cfg: KeycloakConfig, transport: Optional[httpx.BaseTransport] = None
    ) -> None:
        self._cfg = cfg
        self._client = httpx.Client(timeout=10.0, transport=transport)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # --- auth -------------------------------------------------------------
    def _fetch_token(self) -> str:
        resp = self._client.post(
            self._cfg.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._cfg.backend_client_id,
                "client_secret": self._cfg.backend_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + max(int(payload.get("expires_in", 60)) - 30, 10)
        return self._token

    def _auth_header(self) -> dict[str, str]:
        if not self._token or time.time() >= self._token_expiry:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        url = f"{self._cfg.admin_base_url}{path}"
        headers = {**self._auth_header(), **kw.pop("headers", {})}
        resp = self._client.request(method, url, headers=headers, **kw)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{method} {path} -> {resp.status_code}: {resp.text}",
                request=resp.request,
                response=resp,
            )
        return resp

    # --- tenants ----------------------------------------------------------
    def list_tenant_groups(self) -> list[TenantSummary]:
        resp = self._req("GET", "/groups", params={"search": "tenants"})
        out: list[TenantSummary] = []
        for g in resp.json():
            if g.get("name") == "tenants":
                for sub in g.get("subGroups", []):
                    out.append(
                        TenantSummary(
                            id=sub["id"],
                            slug=sub["name"],
                            name=sub.get("attributes", {}).get(
                                "displayName", [sub["name"]]
                            )[0],
                        )
                    )
        return out

    def create_tenant(self, spec: TenantSpec) -> None:
        # Create top-level group /tenants/<slug>. We assume /tenants exists (seeded in realm-export).
        # Find the /tenants parent id.
        parents = self._req("GET", "/groups", params={"search": "tenants"}).json()
        parent_id = next((g["id"] for g in parents if g["name"] == "tenants"), None)
        if not parent_id:
            raise RuntimeError("Parent group /tenants is missing from realm")
        self._req(
            "POST",
            f"/groups/{parent_id}/children",
            json={"name": spec.slug, "attributes": {"displayName": [spec.name]}},
        )
        for role in (f"tenant:{spec.slug}:admin", f"tenant:{spec.slug}:member"):
            self._req("POST", "/roles", json={"name": role})

    def _find_tenant_group_id(self, slug: str) -> str:
        # Look up by path search.
        resp = self._req("GET", "/groups", params={"search": slug})
        for g in resp.json():
            if g.get("name") == slug and g.get("path") == f"/tenants/{slug}":
                return g["id"]
            for sub in g.get("subGroups", []):
                if sub.get("path") == f"/tenants/{slug}":
                    return sub["id"]
        raise LookupError(f"Tenant '{slug}' not found")

    def delete_tenant(self, slug: str) -> None:
        gid = self._find_tenant_group_id(slug)
        self._req("DELETE", f"/groups/{gid}")
        for role in (f"tenant:{slug}:admin", f"tenant:{slug}:member"):
            try:
                self._req("DELETE", f"/roles/{role}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

    # --- tenant users -----------------------------------------------------
    def list_tenant_users(self, slug: str) -> list[TenantUser]:
        gid = self._find_tenant_group_id(slug)
        members = self._req("GET", f"/groups/{gid}/members").json()
        out: list[TenantUser] = []
        for m in members:
            roles = self._req("GET", f"/users/{m['id']}/role-mappings/realm").json()
            role_names = {r["name"] for r in roles}
            if f"tenant:{slug}:admin" in role_names:
                role = "admin"
            elif f"tenant:{slug}:member" in role_names:
                role = "member"
            else:
                role = "member"
            out.append(
                TenantUser(
                    user_id=m["id"],
                    username=m.get("username", ""),
                    email=m.get("email", ""),
                    role=role,
                )
            )
        return out

    def invite_user(self, slug: str, email: str, role: str) -> str:
        """Create user if missing, add to group, assign role, send verify-email action.

        Returns the user_id.
        """
        existing = self._req(
            "GET", "/users", params={"email": email, "exact": "true"}
        ).json()
        if existing:
            user_id = existing[0]["id"]
        else:
            self._req(
                "POST",
                "/users",
                json={
                    "email": email,
                    "username": email,
                    "enabled": True,
                    "emailVerified": False,
                },
            )
            user_id = self._req(
                "GET", "/users", params={"email": email, "exact": "true"}
            ).json()[0]["id"]

        gid = self._find_tenant_group_id(slug)
        self._req("PUT", f"/users/{user_id}/groups/{gid}")
        self._assign_role(user_id, f"tenant:{slug}:{role}")
        # Send invite email with required actions
        self._req(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            json=["VERIFY_EMAIL", "UPDATE_PASSWORD"],
        )
        return user_id

    def set_user_role(self, slug: str, user_id: str, new_role: str) -> None:
        # Remove the opposite role first if present, then assign new.
        opposite = "member" if new_role == "admin" else "admin"
        self._unassign_role(user_id, f"tenant:{slug}:{opposite}")
        self._assign_role(user_id, f"tenant:{slug}:{new_role}")

    def remove_user_from_tenant(self, slug: str, user_id: str) -> None:
        gid = self._find_tenant_group_id(slug)
        try:
            self._req("DELETE", f"/users/{user_id}/groups/{gid}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        for role in (f"tenant:{slug}:admin", f"tenant:{slug}:member"):
            self._unassign_role(user_id, role)

    def _role_repr(self, role_name: str) -> dict:
        return self._req("GET", f"/roles/{role_name}").json()

    def _assign_role(self, user_id: str, role_name: str) -> None:
        role = self._role_repr(role_name)
        self._req("POST", f"/users/{user_id}/role-mappings/realm", json=[role])

    def _unassign_role(self, user_id: str, role_name: str) -> None:
        try:
            role = self._role_repr(role_name)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return
            raise
        try:
            self._req("DELETE", f"/users/{user_id}/role-mappings/realm", json=[role])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
