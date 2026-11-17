"""Copy the database somewhere safe before anything destructive.

SQLite: file copy after a WAL checkpoint, then the copy is opened and counted, so a
truncated backup fails here rather than on restore day.

Postgres/Supabase: ``pg_dump`` if it is on PATH. When it is not, this refuses instead
of pretending: an "backup" that is really just a printed path is worse than none.

    .venv/Scripts/python.exe -m scripts.backup_db
    .venv/Scripts/python.exe -m scripts.backup_db --keep 7
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKUP_DIR = REPO / "var" / "backups"
_SAFE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _count(conn: sqlite3.Connection, name: str) -> int:
    """Identifiers cannot be bound, so the name is whitelisted and then quoted."""
    if not _SAFE_IDENT.fullmatch(name):
        raise ValueError(f"unsafe table name in backup: {name!r}")
    row = conn.execute(
        f'select count(*) from "{name}"'  # noqa: S608 - whitelisted above, cannot be bound
    ).fetchone()
    return int(row[0]) if row else 0


def backup_sqlite(source: Path, keep: int) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{source.stem}-{_stamp()}.db"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(source, target)

    with sqlite3.connect(target) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            ).fetchall()
            # Identifiers cannot be bound as parameters, so they are validated instead:
            # anything that is not a plain identifier is skipped rather than quoted.
            if _SAFE_IDENT.fullmatch(row[0])
        ]
        total = sum(_count(conn, name) for name in names)
    print(f"sqlite backup: {target} ({len(names)} tables, {total} rows)")
    _prune(keep)
    return target


def backup_postgres(url: str, keep: int) -> Path:
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise SystemExit(
            "pg_dump not found on PATH. Install the PostgreSQL client tools, or take a "
            "backup from the Supabase dashboard. Nothing was written."
        )
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"postgres-{_stamp()}.dump"
    plain = url.replace("postgresql+asyncpg://", "postgresql://")
    result = subprocess.run(  # noqa: S603 - fixed argv, pg_dump resolved from PATH
        [pg_dump, "--format=custom", f"--file={target}", plain],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise SystemExit(f"pg_dump failed: {result.stderr[-800:]}")
    print(f"postgres backup: {target} ({target.stat().st_size} bytes)")
    _prune(keep)
    return target


def _prune(keep: int) -> None:
    files = sorted(BACKUP_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)
        print(f"pruned {stale.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="back up the Jarvis database")
    parser.add_argument("--keep", type=int, default=5)
    args = parser.parse_args()

    from apps.api.config import get_settings

    settings = get_settings()
    if settings.is_postgres:
        backup_postgres(settings.database_url, args.keep)
    else:
        prefix = "sqlite+aiosqlite:///"
        if not settings.database_url.startswith(prefix):
            raise SystemExit(f"unsupported DATABASE_URL scheme: {settings.database_url[:24]}")
        source = (REPO / settings.database_url[len(prefix) :].lstrip("./")).resolve()
        if not source.exists():
            raise SystemExit(f"no database at {source}; nothing to back up")
        backup_sqlite(source, args.keep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
