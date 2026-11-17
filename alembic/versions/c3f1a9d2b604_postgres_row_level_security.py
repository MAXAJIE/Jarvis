"""Deny-by-default on Postgres: row level security on every app table.

Supabase exposes a PostgREST endpoint reachable with the project's anon key, which
is visible in the dashboard and meant to be shipped to clients. Without RLS, every
table in this schema would be readable and writable through that endpoint by anyone
holding that key - regardless of the fact that Jarvis itself never uses it.

RLS with no policies is a deny-all for anon/authenticated, while the table owner
(the ``postgres`` role this app connects as) still has full access. That is exactly
the wanted shape: one operator, one connection, nothing reachable from the public
API surface.

The extension-level half (pgvector) is deliberately not here: RAG tier 3 needs an
embedding provider that does not exist in this build, and creating an unused
extension would imply the feature works.

Revision ID: c3f1a9d2b604
Revises: 8b188e2e3797
"""

from __future__ import annotations

from alembic import op

revision: str = "c3f1a9d2b604"
down_revision: str | None = "8b188e2e3797"
branch_labels: str | None = None
depends_on: str | None = None


# Derived from the models, never hand-listed. The first draft of this migration was
# a hand-written list and it was wrong in three places at once: it named a table that
# does not exist (``task_runs``, which would have aborted the migration on PostgreSQL
# with "relation does not exist" - something --sql rendering cannot catch) and missed
# two that do (``task_events``, ``voice_latency``), leaving them world-readable.
# tests/unit/test_postgres_schema.py now fails if this set ever drifts from the models.
def _tables() -> list[str]:
    from apps.api.db.models import Base

    return sorted(name for name in Base.metadata.tables if name != "alembic_version")


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for table in _tables():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in _tables():
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
