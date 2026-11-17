"""Postgres compatibility, tested without a Postgres server.

Two things can be checked with no network and no server, and both have silently
broken this project's class of bug before:

1. The Alembic chain renders valid PostgreSQL DDL. ``--sql`` mode compiles against
   the real dialect, so JSONB, BIGSERIAL, timestamptz, the CHECK constraints and
   the RLS statements either appear or the test fails.
2. The queries the app actually runs compile to PostgreSQL, not just SQLite. A
   ``meta ->> 'key'`` access that only worked on SQLite would be invisible until
   the day the operator switched databases.

What this file does *not* prove: that a live Supabase instance accepts the DDL and
serves the queries. That is ``tests/integration/test_postgres_parity.py``, which
skips - loudly - unless ``JARVIS_TEST_POSTGRES_URL`` points at a real database.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from apps.api.db.models import CostLedgerRow
from apps.api.routes.metrics import _db_health

REPO = Path(__file__).resolve().parents[2]


def _render_sql(url: str) -> str:
    env = {**os.environ, "DATABASE_URL": url, "JARVIS_ENV_FILE": os.devnull}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.fixture(scope="module")
def pg_sql() -> str:
    return _render_sql("postgresql+asyncpg://u:p@db.example.supabase.co:5432/postgres")


def test_migration_renders_postgres_types(pg_sql: str) -> None:
    assert "JSONB" in pg_sql, "JSON columns must be jsonb on Postgres"
    assert "BIGSERIAL" in pg_sql, "ledger/run ids must be BIGSERIAL, not INTEGER"
    assert "TIMESTAMP WITH TIME ZONE" in pg_sql
    # A single leftover SQLite construct means the chain is not portable.
    assert "sqlite" not in pg_sql.lower()
    assert "WITHOUT ROWID" not in pg_sql


def test_migration_keeps_constraints_and_foreign_keys(pg_sql: str) -> None:
    assert "CHECK (kind in (" in pg_sql
    assert pg_sql.count("FOREIGN KEY") >= 10
    assert pg_sql.count("CREATE TABLE") == 15


def test_row_level_security_covers_every_model_table(pg_sql: str) -> None:
    """Supabase exposes PostgREST with a public anon key. Without RLS every table
    here is world-writable through it, whether or not this app uses that API.

    Checked against the models, not a sample: the hand-written first draft of this
    migration named a nonexistent table and missed two real ones.
    """
    from apps.api.db.models import Base

    expected = {name for name in Base.metadata.tables if name != "alembic_version"}
    enabled = set(re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY;", pg_sql))
    assert enabled == expected, f"missing RLS: {sorted(expected - enabled)}"
    # No statement may name a table that the schema does not create.
    created = set(re.findall(r"CREATE TABLE (\w+) \(", pg_sql))
    assert enabled <= created, f"RLS on nonexistent tables: {sorted(enabled - created)}"


def test_rls_is_a_noop_on_sqlite() -> None:
    """The same chain must still migrate the dev database without emitting
    Postgres-only statements."""
    sql = _render_sql("sqlite+aiosqlite:///./var/test-render-only.db")
    assert "ROW LEVEL SECURITY" not in sql


def test_unpriced_ledger_query_compiles_for_postgres() -> None:
    query = select(func.count(CostLedgerRow.id)).where(
        CostLedgerRow.kind == "llm",
        CostLedgerRow.meta["unverified_price"].as_boolean().is_(True),
    )
    rendered = str(
        query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "meta ->> 'unverified_price'" in rendered
    assert "CAST(" in rendered


@pytest.mark.asyncio
async def test_health_names_the_database_in_use() -> None:
    """The health panel must say which database answered, not merely 'reachable'."""
    ok, detail = await _db_health()
    assert ok is True
    assert detail.startswith("sqlite")
