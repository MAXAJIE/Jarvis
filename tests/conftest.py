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
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
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
