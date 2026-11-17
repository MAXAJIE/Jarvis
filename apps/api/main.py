"""FastAPI entrypoint.

Startup order matters: credentials guard, secret key, database, runtime, static
files. If any step refuses, the process exits instead of serving a half-agent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.runtime import Runtime, settings_guard
from apps.api.config import ensure_secret_key, get_settings
from apps.api.db import session as db_session
from apps.api.db.models import Base
from apps.api.routes import approvals, auth_routes, chat, metrics, system, tasks

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


async def init_database() -> None:
    """Dev creates the schema directly; prod must run Alembic before boot."""
    settings = get_settings()
    engine = db_session.configure()
    if settings.is_prod:
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings_guard()
    _ = ensure_secret_key()
    await init_database()
    runtime = Runtime()
    await runtime.start()
    app.state.runtime = runtime
    try:
        yield
    finally:
        await runtime.stop()
        await db_session.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Jarvis",
        version="0.1.0",
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    for router in (
        auth_routes.router,
        tasks.router,
        approvals.router,
        metrics.router,
        system.router,
    ):
        app.include_router(router)
    app.include_router(chat.router)

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/", include_in_schema=False, response_model=None)
        async def index() -> FileResponse | JSONResponse:
            target = WEB_DIST / "index.html"
            if not target.exists():
                return JSONResponse({"detail": "web build missing"}, status_code=500)
            return FileResponse(target)

    return app


app = create_app()
