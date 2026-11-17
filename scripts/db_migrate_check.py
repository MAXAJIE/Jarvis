"""Exercise the migration chain on a throwaway database. Never the live one.

Written after running ``alembic downgrade base`` against ``var/jarvis.db`` and
emptying it: a down/up cycle is a destructive test and belongs on a copy. This
script refuses to touch the configured ``DATABASE_URL`` and hard-exits if asked to.

    .venv/Scripts/python.exe -m scripts.db_migrate_check
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    import os

    env = {**os.environ, "DATABASE_URL": url, "JARVIS_ENV_FILE": os.devnull}
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


def _tables(db: Path) -> list[str]:
    import sqlite3

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        ).fetchall()
    return sorted(row[0] for row in rows)


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="jarvis-migrate-"))
    db = scratch / "migrate-check.db"
    url = f"sqlite+aiosqlite:///{db.as_posix()}"
    from apps.api.config import get_settings

    live = get_settings().database_url
    if live.endswith(db.name) or str(scratch) in live:
        print("refusing to run against the live database")
        return 1

    try:
        for step, args in (
            ("upgrade", ("upgrade", "head")),
            ("downgrade", ("downgrade", "base")),
            ("upgrade-again", ("upgrade", "head")),
        ):
            result = _alembic(url, *args)
            if result.returncode != 0:
                print(f"FAIL {step}: {result.stderr[-1500:]}")
                return 1
            print(f"PASS {step}")
        tables = _tables(db)
        if len(tables) != 15:
            print(f"FAIL expected 15 tables after re-upgrade, found {len(tables)}: {tables}")
            return 1
        print(f"PASS schema restored: {len(tables)} tables")
        print(f"scratch database: {db}")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
