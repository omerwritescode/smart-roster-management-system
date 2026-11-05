"""Create the tables and load the sample data: python -m backend.db.migrate [--fresh]

--fresh drops everything in the public schema first. Use it only on a demo database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from .database import database_url
from .seed import reset

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def run(fresh: bool = False, url: str | None = None) -> None:
    with psycopg.connect(url or database_url(), prepare_threshold=None, autocommit=False) as conn:
        if fresh:
            conn.execute("drop schema public cascade; create schema public;")
            conn.execute("grant all on schema public to public")
        exists = conn.execute("select to_regclass('public.rosters')").fetchone()[0]
        if not exists:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text())
                print(f"Applied {path.name}")
        result = reset(conn)
        print(f"Loaded sample data: {result}")


if __name__ == "__main__":
    run(fresh="--fresh" in sys.argv)
