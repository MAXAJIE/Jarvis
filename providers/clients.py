"""Thin, typed provider clients. No policy logic, no retries beyond one refresh.

Every call is gated by the tool layer before it gets here, and every error is
reduced to a stable type name: provider text never reaches the model (SKILL §4.5).
"""

from __future__ import annotations

import httpx

from apps.api.config import get_settings

TIMEOUT_S = 15.0


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S)


class GoogleAuthError(RuntimeError):
    pass


async def refresh_access_token() -> str:
    """Exchange the stored refresh token for an access token (Gmail scope).

    VERIFY (open item O4): testing-mode OAuth refresh tokens expire in ~7 days.
    Until the app is published, a 400 here means "re-run scripts/google_auth.py".
    """
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise GoogleAuthError("google credentials missing")
    if not settings.google_refresh_token:
        raise GoogleAuthError("google refresh token missing")
    async with _client() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": settings.google_refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise GoogleAuthError(f"token refresh failed: {response.status_code}")
    payload: dict[str, object] = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str):
        raise GoogleAuthError("token refresh returned no access_token")
    return token


async def gmail_get(path: str, params: dict[str, str] | None = None) -> dict[str, object]:
    token = await refresh_access_token()
    async with _client() as client:
        response = await client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise GoogleAuthError(f"gmail read failed: {response.status_code}")
    payload: dict[str, object] = response.json()
    return payload


async def gmail_send(raw_b64: str) -> str:
    token = await refresh_access_token()
    async with _client() as client:
        response = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json={"raw": raw_b64},
            headers={"Authorization": f"Bearer {token}"},
        )
    if response.status_code not in (200, 202):
        raise GoogleAuthError(f"gmail send failed: {response.status_code}")
    payload: dict[str, object] = response.json()
    return str(payload.get("id", ""))


async def telegram_send_message(chat_id: str, text: str) -> dict[str, object]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("telegram token missing")
    async with _client() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
    if response.status_code != 200:
        raise RuntimeError(f"telegram send failed: {response.status_code}")
    payload: dict[str, object] = response.json()
    return payload


async def twilio_place_call(*, to_e164: str, from_e164: str, twiml_url: str, max_s: int) -> str:
    """Place one call with a hard TimeLimit. Never called without an approval row."""
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        raise RuntimeError("twilio credentials missing")
    if not twiml_url:
        raise RuntimeError("twilio webhook base missing")
    async with _client() as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json",
            data={
                "To": to_e164,
                "From": from_e164,
                "Url": twiml_url,
                "TimeLimit": str(max_s),
                "MachineDetection": "Enable",
            },
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        )
    if response.status_code not in (200, 201):
        raise RuntimeError(f"twilio call failed: {response.status_code}")
    payload: dict[str, object] = response.json()
    return str(payload.get("sid", ""))
