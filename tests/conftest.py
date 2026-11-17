"""Shared fixtures.

The database is a real SQLite file per test, with the real models and the real
session factory. The policy engine is never mocked in a test that claims to
prove safety (SKILL §9).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from apps.api.config import reset_settings_cache
from apps.api.db import session as db_session
from apps.api.db.models import Base, Conversation, Message, User


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-a-real-one")
    monkeypatch.setenv("OPERATOR_EMAIL", "operator@example.test")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_ID", "424242")
    monkeypatch.setenv("TWILIO_DEFAULT_LINE_E164", "")
    monkeypatch.setenv("SANDBOX_IMAGE", "")
    monkeypatch.setenv("JARVIS_CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite"))
    # Settings reads .env by default; point it at an empty file so the operator's
    # real provider keys and models cannot reach a test.
    empty_env = tmp_path / "env.test"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("JARVIS_ENV_FILE", str(empty_env))
    # The suite must not see the operator's real .env. Without this, a test that
    # looked harmless called the live Deepgram API with a real key: the run passed
    # or failed depending on the machine, and it spent money doing it.
    for secret in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "CEREBRAS_API_KEY",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "AZURE_SPEECH_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(secret, raising=False)
    reset_settings_cache()
    yield
    os.environ.pop("JARVIS_TEST_LEAK", None)
    reset_settings_cache()


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[dict[str, str]]:
    await db_session.dispose()
    engine = db_session.configure(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ids = {"user_id": "u-test", "conversation_id": "c-test", "thread_id": "t-test"}
    async with db_session.session_scope() as session:
        session.add(
            User(id=ids["user_id"], email="operator@example.test", password_hash="", totp_secret="")
        )
        await session.flush()
        session.add(
            Conversation(id=ids["conversation_id"], user_id=ids["user_id"], transport="web")
        )
        await session.flush()
        session.add(
            Message(
                id="m-1",
                conversation_id=ids["conversation_id"],
                role="user",
                content="I live in Kuala Lumpur",
            )
        )
    yield ids
    await db_session.dispose()


def pytest_collection_modifyitems(items: list[Any]) -> None:  # pragma: no cover
    del items
