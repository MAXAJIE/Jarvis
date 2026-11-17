"""Async engine and session factory.

One process, one user, one engine. Tests call ``configure`` with a temporary SQLite
URL and ``reset``/``dispose`` between cases.

Two dialects are supported on purpose:

* SQLite (``sqlite+aiosqlite``) - the default. Fast, hermetic, no server, and the
  profile the test suite runs on.
* PostgreSQL / Supabase (``postgresql+asyncpg``) - the durable store.

The differences that actually bite are handled here: SQLite needs foreign keys
switched on per connection (they are off by default, silently), and Postgres behind
a transaction pooler needs asyncpg's prepared-statement cache disabled or the second
query in a session fails with DuplicatePreparedStatementError.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_fks(engine: AsyncEngine) -> None:
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _postgres_args(settings: Any) -> dict[str, Any]:
    """Connection arguments for asyncpg.

    ``statement_cache_size=0`` is not an optimisation: behind Supabase's transaction
    pooler (port 6543) the server hands each transaction a different backend, so a
    cached prepared statement from the previous one does not exist any more.
    """
    args: dict[str, Any] = {"server_settings": {"application_name": "jarvis"}}
    if settings.is_pooled_postgres:
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0
    return args


def _prepare_sqlite_path(target: str) -> None:
    """Create the directory a SQLite file lives in.

    ``var/`` is gitignored, so on a fresh clone it does not exist and SQLite cannot
    create ``var/jarvis.db`` inside it - a first boot that dies with "unable to open
    database file" and no hint about why. Cheap to prevent, impossible to guess.
    """
    if not target.startswith("sqlite"):
        return
    database = make_url(target).database
    if not database or database == ":memory:" or database.startswith("file:"):
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def configure(url: str | None = None) -> AsyncEngine:
    global _engine, _factory
    if _engine is not None:
        return _engine
    settings = get_settings()
    target = url or settings.database_url
    _prepare_sqlite_path(target)
    postgres = target.startswith(("postgresql", "postgres"))
    options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if postgres:
        options["pool_size"] = settings.db_pool_size
        options["max_overflow"] = settings.db_max_overflow
        options["connect_args"] = _postgres_args(settings) if url is None else {}
    engine = create_async_engine(target, **options)
    _enable_sqlite_fks(engine)
    _engine = engine
    _factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine


def get_factory() -> async_sessionmaker[AsyncSession]:
    if _factory is None:
        configure()
    assert _factory is not None
    return _factory


async def dispose() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = get_factory()()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()
