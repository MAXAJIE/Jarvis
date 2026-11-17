"""Auth routes: login, logout, whoami."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.auth import (
    COOKIE_NAME,
    MAX_AGE_S,
    issue_token,
    rate_limited,
    require_session,
    secure_cookies,
    verify_password,
    verify_totp,
)
from apps.api.config import get_settings
from apps.api.db.models import User
from apps.api.db.session import session_scope

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1)
    totp: str = ""


class IdentityOut(BaseModel):
    user_id: str
    email: str
    lang_default: str


@router.post("/login", response_model=IdentityOut)
async def login(body: LoginIn, request: Request, response: Response) -> IdentityOut:
    client = request.client.host if request.client else "unknown"
    if rate_limited(client):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, wait a minute")

    settings = get_settings()
    if not settings.operator_password_hash:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "operator credentials are not set up: run scripts/setup_operator.py",
        )
    if body.email.strip().lower() != settings.operator_email.strip().lower():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not verify_password(settings.operator_password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if settings.operator_totp_secret and not verify_totp(settings.operator_totp_secret, body.totp):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid code")

    async with session_scope() as session:
        stmt = select(User).where(User.email == settings.operator_email)
        user = (await session.execute(stmt)).scalars().first()
        if user is None:
            user = User(email=settings.operator_email)
            session.add(user)
            await session.flush()
        user_id = user.id
        lang_default = user.lang_default

    response.set_cookie(
        COOKIE_NAME,
        issue_token(user_id),
        max_age=MAX_AGE_S,
        httponly=True,
        secure=secure_cookies(),
        samesite="strict",
        path="/",
    )
    return IdentityOut(user_id=user_id, email=settings.operator_email, lang_default=lang_default)


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=IdentityOut)
async def me(user_id: str = Depends(require_session)) -> IdentityOut:
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
        return IdentityOut(user_id=user.id, email=user.email, lang_default=user.lang_default)
