from __future__ import annotations

from pathlib import Path

import psycopg


def migration_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


def apply_migrations(database_url: str, directory: Path | None = None) -> list[str]:
    files = sorted((directory or migration_directory()).glob("*.sql"))
    applied_now: list[str] = []
    with psycopg.connect(database_url) as conn:
        conn.execute("set search_path to public, extensions")
        conn.execute(
            """
            create table if not exists public.schema_migrations (
                version text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        conn.commit()
        for path in files:
            existing = conn.execute(
                "select 1 from public.schema_migrations where version = %s", (path.name,)
            ).fetchone()
            if existing:
                continue
            try:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into public.schema_migrations (version) values (%s)", (path.name,)
                )
                conn.commit()
                applied_now.append(path.name)
            except Exception:
                conn.rollback()
                raise
    return applied_now
