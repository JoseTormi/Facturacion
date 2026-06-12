from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from secrets import token_urlsafe
from typing import Any

from fastapi import HTTPException, Request, Response, status

from saef.config import Settings, settings


AUTH_COOKIE_NAME = "saef_session"


def verify_credentials(username: str, password: str, config: Settings = settings) -> bool:
    return hmac.compare_digest(username, config.admin_username) and hmac.compare_digest(
        password,
        config.admin_password,
    )


def create_session_token(username: str, config: Settings = settings) -> str:
    expires_at = int(time.time()) + max(config.auth_session_minutes, 1) * 60
    payload = {
        "sub": username,
        "exp": expires_at,
        "nonce": token_urlsafe(12),
    }
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload, config.auth_secret_key)
    return f"{encoded_payload}.{signature}"


def set_session_cookie(response: Response, token: str, config: Settings = settings) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=max(config.auth_session_minutes, 1) * 60,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, config: Settings = settings) -> None:
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        httponly=True,
        secure=config.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def authenticated_username(request: Request, config: Settings = settings) -> str | None:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None

    payload = verify_session_token(token, config)
    if not payload:
        return None

    username = payload.get("sub")
    if not isinstance(username, str):
        return None
    return username


def require_authenticated_user(request: Request) -> str:
    username = authenticated_username(request)
    if username:
        return username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Debes iniciar sesion.",
    )


def verify_session_token(token: str, config: Settings = settings) -> dict[str, Any] | None:
    try:
        encoded_payload, signature = token.split(".", maxsplit=1)
    except ValueError:
        return None

    expected_signature = _sign(encoded_payload, config.auth_secret_key)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64decode(encoded_payload))
    except (ValueError, json.JSONDecodeError):
        return None

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        return None
    if payload.get("sub") != config.admin_username:
        return None
    return payload


def _sign(encoded_payload: str, secret_key: str) -> str:
    digest = hmac.new(
        secret_key.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
