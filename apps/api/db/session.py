"""Async engine and session factory.

One process, one user, one engine. Tests call ``configure`` with an in-memory
SQLite URL and ``reset`` between cases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
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


def configure(url: str | None = None) -> AsyncEngine:
    global _engine, _factory
    if _engine is not None:
        return _engine
    target = url or get_settings().database_url
    engine = create_async_engine(target, future=True, pool_pre_ping=True)
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
