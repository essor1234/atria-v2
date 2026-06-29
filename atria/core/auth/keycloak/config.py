from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class AuthMode(str, Enum):
    NONE = "none"
    KEYCLOAK = "keycloak"


@dataclass(frozen=True)
class KeycloakConfig:
    auth_mode: AuthMode
    internal_url: str  # used by backend <-> keycloak (e.g. http://keycloak:8080)
    public_url: str  # used for issuer matching (e.g. http://localhost:8082)
    realm: str
    backend_client_id: str
    backend_client_secret: str
    jwks_cache_ttl_seconds: int = 300

    @property
    def issuer(self) -> str:
        return f"{self.public_url.rstrip('/')}/realms/{self.realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def admin_base_url(self) -> str:
        return f"{self.internal_url.rstrip('/')}/admin/realms/{self.realm}"

    @classmethod
    def from_env(cls) -> "KeycloakConfig":
        mode_raw = os.getenv("AUTH_MODE", "none").lower()
        mode = AuthMode(mode_raw) if mode_raw in {m.value for m in AuthMode} else AuthMode.NONE

        if mode is AuthMode.NONE:
            return cls(
                auth_mode=mode,
                internal_url="",
                public_url="",
                realm="",
                backend_client_id="",
                backend_client_secret="",
            )

        secret = os.getenv("KEYCLOAK_BACKEND_CLIENT_SECRET", "")
        if not secret:
            raise RuntimeError("KEYCLOAK_BACKEND_CLIENT_SECRET is required when AUTH_MODE=keycloak")

        return cls(
            auth_mode=mode,
            internal_url=os.getenv("KEYCLOAK_URL", "http://keycloak:8080"),
            public_url=os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8082"),
            realm=os.getenv("KEYCLOAK_REALM", "atria"),
            backend_client_id=os.getenv("KEYCLOAK_BACKEND_CLIENT_ID", "atria-backend"),
            backend_client_secret=secret,
        )
