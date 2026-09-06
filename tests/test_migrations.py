from __future__ import annotations

from scotland_facts.migrations import apply_migrations


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class MigrationConnection:
    def __init__(self):
        self.applied = set()
        self.executed_sql = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("select 1 from public.schema_migrations"):
            return Result((1,) if params[0] in self.applied else None)
        if normalized.startswith("insert into public.schema_migrations"):
            self.applied.add(params[0])
            return Result()
        if not normalized.startswith("set search_path") and not normalized.startswith(
            "create table if not exists public.schema_migrations"
        ):
            self.executed_sql.append(sql.strip())
        return Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_migrations_run_lexically_and_are_repeatable(monkeypatch, tmp_path):
    (tmp_path / "002_second.sql").write_text("select 'second';", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("select 'first';", encoding="utf-8")
    connection = MigrationConnection()
    monkeypatch.setattr(
        "scotland_facts.migrations.psycopg.connect", lambda database_url: connection
    )

    assert apply_migrations("postgresql://redacted", tmp_path) == [
        "001_first.sql",
        "002_second.sql",
    ]
    assert connection.executed_sql == ["select 'first';", "select 'second';"]
    assert apply_migrations("postgresql://redacted", tmp_path) == []
    assert connection.rollbacks == 0
