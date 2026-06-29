"""Authentication API endpoints (Keycloak OIDC + legacy email fallback)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from atria.core.auth.keycloak.config import AuthMode
from atria.web.state import get_state

SECRET_KEY = "change-me"
TOKEN_COOKIE = "atria_session"
TOKEN_TTL_SECONDS = 60 * 60 * 24
PKCE_COOKIE = "atria_oidc_pkce"
PKCE_TTL_SECONDS = 600
KC_LOGIN_CLIENT_ID = "atria-web"

serializer = URLSafeTimedSerializer(SECRET_KEY)


class AuthResponse(BaseModel):
    username: str
    email: Optional[str] = None
    role: str
    workspace_path: Optional[str] = None
    project_id: Optional[int] = None


class LoginRequest(BaseModel):
    email: str


class ModeResponse(BaseModel):
    mode: str


class LogoutResponse(BaseModel):
    status: str
    end_session_url: Optional[str] = None


router = APIRouter(prefix="/api/auth", tags=["auth"])


def create_token(user_id: str) -> str:
    return serializer.dumps({"sub": user_id, "ts": datetime.utcnow().isoformat()})


def verify_token(token: str) -> str:
    try:
        data = serializer.loads(token, max_age=TOKEN_TTL_SECONDS)
        return data["sub"]
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _kc_services():
    return getattr(get_state(), "keycloak", None)


def _is_keycloak_mode() -> bool:
    return _kc_services() is not None


def _safe_next(value: Optional[str]) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/chat"
    return value


@router.get("/mode", response_model=ModeResponse)
def get_mode() -> ModeResponse:
    """Tell the SPA which login UI to render."""
    return ModeResponse(
        mode=AuthMode.KEYCLOAK.value if _is_keycloak_mode() else AuthMode.NONE.value
    )


@router.get("/keycloak/login")
async def keycloak_login(request: Request, next: str = "/chat") -> Response:
    services = _kc_services()
    if services is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Keycloak not configured")

    cfg = services.config
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode()).digest())

    pkce_cookie = serializer.dumps(
        {"state": state, "verifier": code_verifier, "next": _safe_next(next)}
    )

    redirect_uri = str(request.url_for("keycloak_callback"))
    authorize_url = (
        f"{cfg.public_url.rstrip('/')}/realms/{cfg.realm}/protocol/openid-connect/auth"
        f"?{urlencode({
            'response_type': 'code',
            'client_id': KC_LOGIN_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'scope': 'openid profile email',
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
        })}"
    )

    resp = RedirectResponse(url=authorize_url, status_code=307)
    resp.set_cookie(
        PKCE_COOKIE,
        pkce_cookie,
        max_age=PKCE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/keycloak/callback", name="keycloak_callback")
async def keycloak_callback(request: Request, code: str = "", state: str = "") -> Response:
    services = _kc_services()
    if services is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Keycloak not configured")
    if not code or not state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing code/state")

    pkce_raw = request.cookies.get(PKCE_COOKIE)
    if not pkce_raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing PKCE cookie")
    try:
        pkce = serializer.loads(pkce_raw, max_age=PKCE_TTL_SECONDS)
    except BadSignature as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid PKCE cookie") from exc
    if pkce.get("state") != state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "State mismatch")

    cfg = services.config
    redirect_uri = str(request.url_for("keycloak_callback"))
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            cfg.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": KC_LOGIN_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": pkce["verifier"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if token_resp.status_code >= 400:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Token exchange failed: {token_resp.text}",
        )
    tokens = token_resp.json()

    try:
        claims = services.validator.validate(tokens["id_token"])
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid id_token: {exc}") from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token missing email claim")
    username_seed = claims.get("preferred_username") or email.split("@")[0]

    state_obj = get_state()
    user_store = state_obj.user_store
    user = await user_store.get_by_email(email)
    if not user:
        candidate = username_seed
        counter = 1
        while await user_store.get_by_username(candidate):
            candidate = f"{username_seed}{counter}"
            counter += 1
        user = await user_store.create_user(candidate, password_hash="", email=email)

    from atria.web.dependencies.workspace import ensure_user_workspace

    await ensure_user_workspace(user.id)

    session_token = create_token(str(user.id))
    next_path = _safe_next(pkce.get("next"))

    resp = RedirectResponse(url=next_path, status_code=303)
    resp.set_cookie(
        TOKEN_COOKIE,
        session_token,
        httponly=True,
        samesite="lax",
        max_age=TOKEN_TTL_SECONDS,
    )
    resp.delete_cookie(PKCE_COOKIE)
    return resp


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, response: Response) -> AuthResponse:
    if _is_keycloak_mode():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Email login is disabled when AUTH_MODE=keycloak. Use GET /api/auth/keycloak/login.",
        )

    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    state = get_state()
    user_store = state.user_store

    user = await user_store.get_by_email(email)
    if not user:
        username = email.split("@")[0]
        base = username
        counter = 1
        while await user_store.get_by_username(username):
            username = f"{base}{counter}"
            counter += 1
        user = await user_store.create_user(username, password_hash="", email=email)

    from atria.web.dependencies.workspace import ensure_user_workspace

    workspace = await ensure_user_workspace(user.id)

    token = create_token(str(user.id))
    response.set_cookie(
        TOKEN_COOKIE, token, httponly=True, samesite="lax", max_age=TOKEN_TTL_SECONDS
    )
    return AuthResponse(
        username=user.username,
        email=user.email,
        role=user.role,
        workspace_path=str(workspace.workspace_path),
        project_id=workspace.project_id,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(response: Response) -> LogoutResponse:
    response.delete_cookie(TOKEN_COOKIE)
    services = _kc_services()
    if services is None:
        return LogoutResponse(status="success")
    cfg = services.config
    end_session_url = (
        f"{cfg.public_url.rstrip('/')}/realms/{cfg.realm}/protocol/openid-connect/logout"
    )
    return LogoutResponse(status="success", end_session_url=end_session_url)


@router.get("/me", response_model=AuthResponse)
async def get_me(request: Request) -> AuthResponse:
    token = request.cookies.get(TOKEN_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id_str = verify_token(token)
    state = get_state()
    user = await state.user_store.get_by_id(int(user_id_str))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    from atria.web.dependencies.workspace import ensure_user_workspace

    workspace = await ensure_user_workspace(user.id)
    return AuthResponse(
        username=user.username,
        email=user.email,
        role=user.role,
        workspace_path=str(workspace.workspace_path),
        project_id=workspace.project_id,
    )
