# Keycloak Multi-Tenant Authentication

**Status:** Draft
**Date:** 2026-06-17
**Scope:** Add Keycloak to the docker-compose stack, integrate OIDC auth into the FastAPI backend and React web-ui, and build a thin admin UI for tenant and user management. Keycloak is the source of truth for tenants and users.

## Goals

- Multi-tenant authentication where a single user can belong to multiple tenants and switch between them without re-login.
- OIDC Authorization Code + PKCE login flow from the SPA.
- Keycloak Admin API used by the Atria backend (via service account) to manage tenants and users.
- A custom admin UI inside the existing web-ui for tenant CRUD, user invites, and a super-admin dashboard.
- Local-dev `docker compose up` runs the full stack with auth enabled by default.

## Non-Goals

- Tagging Atria's own DB rows with `tenant_id`. This spec sets up the auth plumbing and exposes a `CurrentPrincipal`; a follow-up spec sweeps data models for tenant scoping.
- Per-tenant identity providers (SAML, social login).
- Production-hardened Keycloak deployment (TLS, reverse proxy, separate DB host, secret management).
- Audit log UI.

## Architecture Overview

```
Browser (web-ui SPA)
   │ 1. redirect to Keycloak (OIDC code+PKCE)
   ▼
Keycloak  ──── Postgres (`keycloak` database, same `db` container)
   │ 2. ID/access token (JWT)
   ▼
Browser  ─── bearer JWT ───►  FastAPI (atria)
                                  │
                                  ├─ Validates JWT via Keycloak JWKS (cached)
                                  ├─ Resolves tenant from token claims + header
                                  └─ Admin endpoints → Keycloak Admin API (service account)
```

**Tenant model.** Single Keycloak realm `atria`. Tenants are realm groups under `/tenants/<tenant-slug>`. A user's tenant memberships are their group paths. Their role within a tenant is a realm role named `tenant:<slug>:<role>` where `role ∈ {admin, member}`. Platform super-admins get the realm role `platform:admin`.

**Clients.**
- `atria-web` — public OIDC client, PKCE required, redirect URIs include the web-ui origin.
- `atria-backend` — confidential client with `service-accounts-enabled` and the `realm-management` roles `manage-users`, `manage-clients`, `view-realm`. Used by FastAPI to call the Admin API.

## Token Shape and Tenant Resolution

Access token (relevant claims):

```json
{
  "sub": "user-uuid",
  "email": "alice@acme.com",
  "preferred_username": "alice",
  "groups": ["/tenants/acme", "/tenants/globex"],
  "realm_access": { "roles": ["tenant:acme:admin", "tenant:globex:member"] }
}
```

The active tenant is **not** in the token. The SPA picks it via a tenant switcher and sends `X-Atria-Tenant: <slug>` on every API request.

FastAPI dependency `get_current_principal`:

1. Validate JWT signature and `exp` via the cached Keycloak JWKS.
2. Read `X-Atria-Tenant` header → `requested`.
3. Assert `/tenants/<requested>` is in the `groups` claim, else 403.
4. Find the role in `realm_access.roles` matching `tenant:<requested>:*`.
5. Inject `CurrentPrincipal { user_id, tenant_id, tenant_role, is_platform_admin }`.

**Why a header instead of one-token-per-tenant:** simpler, no re-login on switch, the claim is still authoritative — the backend cannot be tricked into a tenant the user does not belong to.

## Admin UI and Admin API Surface

New web-ui routes under `/admin`:

- `/admin/tenants` — super-admin only. List, create, delete tenants.
- `/admin/tenants/:id/users` — tenant admin or super-admin. Invite, remove, change role.
- `/admin/me/tenants` — any user. Tenant switcher.

New FastAPI module `atria/web/api/admin.py`:

Super-admin scope:
- `GET /api/admin/tenants`
- `POST /api/admin/tenants` `{slug, name}` — creates group `/tenants/<slug>` and realm roles `tenant:<slug>:admin`, `tenant:<slug>:member`.
- `DELETE /api/admin/tenants/{slug}` — deletes group and both roles.

Tenant-admin scope (requires `tenant:<slug>:admin` or `platform:admin`):
- `GET /api/admin/tenants/{slug}/users`
- `POST /api/admin/tenants/{slug}/invites` `{email, role}` — uses Keycloak's "send invite email" action; if the user does not exist, creates them with `enabled=false` until verified.
- `PATCH /api/admin/tenants/{slug}/users/{user_id}` `{role}` — swap realm role.
- `DELETE /api/admin/tenants/{slug}/users/{user_id}` — remove from group and revoke roles.

Self:
- `GET /api/me` — returns principal and the list of tenants from the token's `groups` claim.

A thin Python wrapper `atria/core/auth/keycloak_admin.py` (httpx) handles service-account token caching and refresh. A single FastAPI dependency factory `require_role(...)` accepts either a literal role like `platform:admin` or a callable `(principal, path_params) -> bool` for tenant-scoped checks.

## Docker Compose and Configuration

`schema.sql` gains a `CREATE DATABASE keycloak;` at the top so Postgres init creates the second database. Keycloak manages its own schema.

`docker-compose.yml` adds:

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    restart: unless-stopped
    command: ["start-dev", "--import-realm"]
    environment:
      - KC_DB=postgres
      - KC_DB_URL=jdbc:postgresql://db:5432/keycloak
      - KC_DB_USERNAME=atria
      - KC_DB_PASSWORD=atria
      - KC_HOSTNAME=localhost
      - KC_HTTP_ENABLED=true
      - KEYCLOAK_ADMIN=admin
      - KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD:-admin}
    ports:
      - "8082:8080"
    volumes:
      - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080; echo -e 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\n\\r\\n' >&3; cat <&3 | grep -q '200 OK'"]
      interval: 10s
      timeout: 5s
      retries: 10
```

The `atria` service gains:

```yaml
      - KEYCLOAK_URL=http://keycloak:8080
      - KEYCLOAK_REALM=atria
      - KEYCLOAK_BACKEND_CLIENT_ID=atria-backend
      - KEYCLOAK_BACKEND_CLIENT_SECRET=${KEYCLOAK_BACKEND_CLIENT_SECRET}
      - KEYCLOAK_PUBLIC_URL=http://localhost:8082
      - AUTH_MODE=keycloak
    depends_on:
      keycloak:
        condition: service_healthy
```

**Realm bootstrap.** A committed file `keycloak/realm-export.json` configures the `atria` realm with both clients, the empty `/tenants` parent group, the `platform:admin` realm role, and one seed super-admin user (dev only). `--import-realm` imports on first boot only; subsequent edits done via the API or admin console persist in Postgres.

**Dev vs prod.** `start-dev` is used here (HTTP, embedded). A production override (TLS, `start`, real hostname, separate DB) is out of scope for this spec.

## Backwards Compatibility / Rollout

Atria currently has no auth. To avoid breaking local workflows that bypass compose:

1. Add `AUTH_MODE=keycloak|none` env var. Default in code is `none`.
2. When `AUTH_MODE=none`, FastAPI injects a hardcoded principal `(user=dev, tenant=default, role=admin)`. All tenant checks pass. Useful for `make run` outside Docker.
3. When `AUTH_MODE=keycloak`, the dependency validates JWTs as described.
4. `docker-compose.yml` ships with `AUTH_MODE=keycloak` so the default compose-up uses auth.
5. No data migration: tenants live in Keycloak, not Atria's Postgres.

## Testing

**Unit.** Mock `KeycloakAdminClient`; test `require_role`, token-claim parsing, tenant resolution, role-prefix logic. Use `httpx.MockTransport` for the Admin API wrapper.

**Integration.** Spin up `db` + `keycloak` in CI, seed the test realm, mint tokens via a Direct Access Grant test client, and hit FastAPI endpoints end-to-end. Lives in `tests/integration/test_auth_keycloak.py`.

**E2E (manual, per `CLAUDE.md`).** `make run`, log in as the seed super-admin, create a tenant, invite a user, switch tenants, confirm cross-tenant access returns 403.

## File Layout (new)

```
keycloak/
  realm-export.json
atria/core/auth/
  __init__.py
  keycloak_admin.py        # httpx wrapper, service-account token cache
  jwt.py                   # JWKS fetch, token validation
  principal.py             # CurrentPrincipal, get_current_principal, require_role
atria/web/api/
  admin.py                 # tenant + user admin endpoints
  me.py                    # /api/me
web-ui/src/pages/admin/
  TenantsPage.tsx
  TenantUsersPage.tsx
  TenantSwitcher.tsx
web-ui/src/auth/
  oidc.ts                  # PKCE flow, token storage, refresh
tests/integration/
  test_auth_keycloak.py
```

## Open Follow-Ups

- Sweep Atria's data models to add `tenant_id` columns and filter all queries by `CurrentPrincipal.tenant_id`. Separate spec.
- Production deployment hardening for Keycloak.
- Per-tenant identity providers.
- Audit log surface.
