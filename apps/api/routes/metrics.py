"""Metrics and health.

``/api/health`` returns 503 naming every component that is not ready. It never
returns a green status to look good: a green health check with an empty
DEEPGRAM_API_KEY is exactly the silent degradation PLANBOOK §5.3 forbids.
"""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from apps.api.auth import require_session
from apps.api.config import get_settings
from apps.api.db.session import session_scope
from apps.api.services.budget import dashboard

router = APIRouter(tags=["ops"])

MIN_DISK_FREE_PERCENT = 10.0


async def _db_health() -> tuple[bool, str]:
    """Reachable *and* which database. "db reachable" is not enough: SQLite when the
    operator expects Supabase is the silent fallback this project forbids."""
    settings = get_settings()
    label = "postgres" if settings.is_postgres else "sqlite"
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
            if settings.is_postgres:
                name = (await session.execute(text("SELECT current_database()"))).scalar()
                label = f"postgres {name}"
            else:
                label = "sqlite"
        return True, label + (" (pooler)" if settings.is_pooled_postgres else "")
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        return False, f"{label}: {type(exc).__name__}"


def _component(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"component": name, "ok": ok, "detail": detail}


@router.get("/api/health")
async def health(response: Response) -> dict[str, Any]:
    settings = get_settings()
    components: list[dict[str, Any]] = []

    db_ok, db_detail = await _db_health()
    components.append(_component("db", db_ok, db_detail))

    llm_ok = settings.llm_configured
    components.append(
        _component(
            "llm",
            llm_ok,
            f"provider={settings.llm_provider}"
            if llm_ok
            else f"provider={settings.llm_provider}"
            + (
                f" ({settings.llm_key_env_name} is empty)"
                if settings.llm_provider != "stub"
                else " (stub: no real model, no real answers)"
            ),
        )
    )

    for name, configured, hint in (
        ("twilio", bool(settings.twilio_account_sid and settings.twilio_auth_token), "TWILIO_*"),
        ("deepgram", bool(settings.deepgram_api_key), "DEEPGRAM_API_KEY"),
        ("tts", settings.tts_configured, settings.tts_key_env_name),
        ("telegram", bool(settings.telegram_bot_token), "TELEGRAM_BOT_TOKEN"),
        ("google", bool(settings.google_client_id and settings.google_refresh_token), "GOOGLE_*"),
        ("sandbox", bool(settings.sandbox_image), "SANDBOX_IMAGE"),
    ):
        components.append(
            _component(name, configured, "configured" if configured else f"{hint} is empty")
        )

    usage = shutil.disk_usage(".")
    free_percent = usage.free / usage.total * 100
    components.append(
        _component(
            "disk",
            free_percent > MIN_DISK_FREE_PERCENT,
            f"{free_percent:.1f}% free",
        )
    )

    ready = all(part["ok"] for part in components)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ready else "degraded",
        "app_env": settings.app_env,
        "components": components,
        "missing": [part["component"] for part in components if not part["ok"]],
    }


@router.get("/api/metrics/dashboard")
async def metrics(user_id: str = Depends(require_session)) -> dict[str, Any]:
    data = await dashboard()
    data["user_id"] = user_id
    return data
