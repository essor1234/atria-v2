import time
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from atria.core.auth.keycloak.config import AuthMode, KeycloakConfig
from atria.core.auth.keycloak.jwt import JwksCache, TokenValidator, InvalidTokenError


def _make_cfg() -> KeycloakConfig:
    return KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
        jwks_cache_ttl_seconds=60,
    )


def _generate_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_numbers = key.public_key().public_numbers()
    import base64

    def b64url_uint(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": b64url_uint(pub_numbers.n),
        "e": b64url_uint(pub_numbers.e),
    }
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem, jwk


def _sign(payload: dict, pem: bytes) -> str:
    return pyjwt.encode(payload, pem, algorithm="RS256", headers={"kid": "test-key"})


def test_validator_accepts_valid_token():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {
            "iss": cfg.issuer,
            "sub": "user-1",
            "aud": "account",
            "exp": now + 60,
            "iat": now,
            "email": "a@b.c",
            "preferred_username": "a",
            "groups": ["/tenants/acme"],
            "realm_access": {"roles": ["tenant:acme:admin"]},
        },
        pem,
    )
    claims = validator.validate(token)
    assert claims["sub"] == "user-1"
    assert claims["groups"] == ["/tenants/acme"]


def test_validator_rejects_wrong_issuer():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {"iss": "http://evil/realms/atria", "sub": "x", "aud": "account", "exp": now + 60, "iat": now},
        pem,
    )
    with pytest.raises(InvalidTokenError):
        validator.validate(token)


def test_validator_rejects_expired_token():
    pem, jwk = _generate_keypair()
    cfg = _make_cfg()
    cache = JwksCache(cfg, fetcher=lambda: {"keys": [jwk]})
    validator = TokenValidator(cfg, cache)
    now = int(time.time())
    token = _sign(
        {"iss": cfg.issuer, "sub": "x", "aud": "account", "exp": now - 5, "iat": now - 60},
        pem,
    )
    with pytest.raises(InvalidTokenError):
        validator.validate(token)


def test_jwks_cache_refetches_after_ttl():
    pem, jwk = _generate_keypair()
    cfg = KeycloakConfig(
        auth_mode=AuthMode.KEYCLOAK,
        internal_url="http://keycloak:8080",
        public_url="http://localhost:8082",
        realm="atria",
        backend_client_id="atria-backend",
        backend_client_secret="shh",
        jwks_cache_ttl_seconds=0,
    )
    calls = MagicMock(return_value={"keys": [jwk]})
    cache = JwksCache(cfg, fetcher=calls)
    cache.get_key("test-key")
    cache.get_key("test-key")
    assert calls.call_count == 2
