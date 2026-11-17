"""Single-user auth: argon2 password + TOTP, signed session cookie, login rate limit.

One user (D-17). No registration, no invites, no roles. The cookie is signed with
SECRET_KEY, HttpOnly, SameSite=Strict, and Secure whenever the app is served over
https. A stolen cookie dies when SECRET_KEY is rotated.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pyotp import TOTP

from apps.api.config import ensure_secret_key, get_settings

COOKIE_NAME = "jarvis_session"
MAX_AGE_S = 7 * 24 * 3600
_hasher = PasswordHasher()
_attempts: dict[str, deque[float]] = defaultdict(deque)
WINDOW_S = 60.0
MAX_ATTEMPTS = 5


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except VerifyMismatchError:
        return False


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return TOTP(secret).verify(code, valid_window=1)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(ensure_secret_key(), salt="jarvis-session")


def issue_token(user_id: str) -> str:
    token: str = _serializer().dumps({"uid": user_id})
    return token


def read_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = _serializer().loads(token, max_age=MAX_AGE_S)
    except (BadSignature, SignatureExpired):
        return None
    uid = payload.get("uid") if isinstance(payload, dict) else None
    return uid if isinstance(uid, str) else None


def rate_limited(key: str) -> bool:
    """Five attempts a minute per key. Returns True when the caller must wait."""
    now = time.monotonic()
    bucket = _attempts[key]
    while bucket and now - bucket[0] > WINDOW_S:
        bucket.popleft()
    if len(bucket) >= MAX_ATTEMPTS:
        return True
    bucket.append(now)
    return False


def reset_rate_limit() -> None:
    _attempts.clear()


def secure_cookies() -> bool:
    return get_settings().app_base_url.startswith("https://")


async def require_session(request: Request) -> str:
    user_id = read_token(request.cookies.get(COOKIE_NAME))
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not signed in")
    return user_id
