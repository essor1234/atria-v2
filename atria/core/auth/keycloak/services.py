# atria/core/auth/keycloak/services.py
from __future__ import annotations

from dataclasses import dataclass

from atria.core.auth.keycloak.admin_client import KeycloakAdminClient
from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import JwksCache, TokenValidator


@dataclass(frozen=True)
class KeycloakServices:
    config: KeycloakConfig
    validator: TokenValidator
    admin: KeycloakAdminClient

    @classmethod
    def from_env(cls) -> "KeycloakServices | None":
        cfg = KeycloakConfig.from_env()
        if cfg.auth_mode is not AuthMode.KEYCLOAK:
            return None
        cache = JwksCache(cfg)
        validator = TokenValidator(cfg, cache)
        admin = KeycloakAdminClient(cfg)
        return cls(config=cfg, validator=validator, admin=admin)
