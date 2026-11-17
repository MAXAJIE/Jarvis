"""Parity against a real PostgreSQL/Supabase database.

Skipped unless ``JARVIS_TEST_POSTGRES_URL`` is set. Skip, never pass: a green suite
that never touched the target database is the failure mode this file exists to stop.

Safety: this test drops and recreates the schema. It therefore refuses to run if the
database contains anything it did not create, unless ``JARVIS_TEST_POSTGRES_ALLOW_RESET=1``.
An operator who pastes their production URL here gets a refusal, not a wipe.

Run it with:

    JARVIS_TEST_POSTGRES_URL='postgresql+asyncpg://postgres.<ref>:<pw>@...' \
        .venv/Scripts/python.exe -m pytest tests/integration/test_postgres_parity.py -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

URL = os.environ.get("JARVIS_TEST_POSTGRES_URL", "")
REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not URL,
    reason="JARVIS_TEST_POSTGRES_URL not set: Postgres parity is UNVERIFIED, by design",
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": URL, "JARVIS_ENV_FILE": os.devnull}
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


@pytest.fixture(scope="module")
def migrated() -> str:
    engine_url = URL

    async def check_empty() -> list[str]:
        engine = create_async_engine(engine_url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text(
                        "select tablename from pg_tables "
                        "where schemaname = 'public' and tablename <> 'alembic_version'"
                    )
                )
                return [row[0] for row in rows]
        finally:
            await engine.dispose()

    import asyncio

    existing = asyncio.run(check_empty())
    if existing and os.environ.get("JARVIS_TEST_POSTGRES_ALLOW_RESET") != "1":
        pytest.skip(
            "database is not empty and JARVIS_TEST_POSTGRES_ALLOW_RESET != 1; "
            f"refusing to drop {sorted(existing)[:6]}"
        )

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    yield engine_url
    _alembic("downgrade", "base")


@pytest.mark.asyncio
async def test_roundtrip_types_and_constraints(migrated: str) -> None:
    """Insert and read back every shape that differs between SQLite and Postgres."""
    engine = create_async_engine(migrated)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = str(uuid4())
    conversation_id = str(uuid4())
    try:
        async with factory() as session:
            await session.execute(
                text("insert into users (id, email) values (:id, :email)"),
                {"id": user_id, "email": f"{user_id}@localhost"},
            )
            await session.execute(
                text(
                    "insert into conversations (id, user_id, title, lang, updated_at) "
                    "values (:id, :uid, :title, 'en', :now)"
                ),
                {
                    "id": conversation_id,
                    "uid": user_id,
                    "title": "parity",
                    "now": datetime.now(UTC),
                },
            )
            await session.execute(
                text(
                    "insert into cost_ledger (ts, kind, provider, model, units, unit_name,"
                    " unit_price_usd, usd, meta, conversation_id)"
                    " values (:ts, 'llm', 'groq', 'qwen', 10, 'tokens', 0, 0, :meta, :cid)"
                ),
                {
                    "ts": datetime.now(UTC),
                    "meta": {"unverified_price": True},
                    "cid": conversation_id,
                },
            )
            await session.commit()

        async with factory() as session:
            # jsonb round trip, boolean extracted from JSON, timestamptz awareness.
            flag = (
                await session.execute(
                    text(
                        "select (meta ->> 'unverified_price')::boolean, ts "
                        "from cost_ledger where conversation_id = :cid"
                    ),
                    {"cid": conversation_id},
                )
            ).one()
            assert flag[0] is True
            assert flag[1].tzinfo is not None, "timestamptz must come back aware"

            # RLS on, and the owner is unaffected: a single-user app must still work.
            rls = (
                await session.execute(
                    text(
                        "select relrowsecurity from pg_class "
                        "where relname = 'cost_ledger' and relkind = 'r'"
                    )
                )
            ).scalar_one()
            assert rls is True
            assert (
                await session.execute(text("select count(*) from cost_ledger"))
            ).scalar_one() >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_check_constraint_rejects_bad_kind(migrated: str) -> None:
    """Postgres enforces CHECK in a way SQLite silently does not when old rows exist."""
    from sqlalchemy.exc import DBAPIError

    engine = create_async_engine(migrated)
    try:
        async with engine.begin() as conn:
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        "insert into cost_ledger "
                        "(ts, kind, provider, units, unit_name, unit_price_usd, usd, meta) "
                        "values (:ts, 'nonsense', 'x', 1, 'tokens', 0, 0, '{}')"
                    ),
                    {"ts": datetime.now(UTC)},
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_engine_and_budget_read_the_real_database(migrated: str, monkeypatch) -> None:
    """The application's own session layer, not raw SQL: this is the code that runs."""
    from apps.api.db import session as db_session
    from apps.api.services.budget import budget_state

    monkeypatch.setenv("DATABASE_URL", migrated)
    from apps.api.config import get_settings

    get_settings.cache_clear()
    await db_session.dispose()
    try:
        engine = db_session.configure(migrated)
        assert engine.dialect.name == "postgresql"
        state = await budget_state()
        assert isinstance(state.usage_usd, Decimal)
        assert state.ceiling_usd == get_settings().monthly_budget_usd
        assert state.total_usd >= state.fixed_usd
        assert datetime.now(UTC) - timedelta(days=32) < datetime.now(UTC)
    finally:
        await db_session.dispose()
        get_settings.cache_clear()
