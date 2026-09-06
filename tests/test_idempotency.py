from __future__ import annotations

import threading
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from scotland_facts.db import Database
from scotland_facts.models import RunType
from scotland_facts.orchestrator import make_run_key, run_workflow


def test_daily_run_key_uses_eastern_date():
    instant = datetime(2026, 9, 6, 3, 0, tzinfo=ZoneInfo("UTC"))
    assert make_run_key(False, instant) == "daily:2026-09-05"


def test_dry_run_keys_never_use_daily_boundary():
    key = make_run_key(True, datetime(2026, 9, 6, 12, tzinfo=ZoneInfo("UTC")))
    assert key.startswith("dryrun:2026-09-06T080000:")


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class SharedRunTable:
    def __init__(self):
        self.rows = {}
        self.lock = threading.Lock()


class ConflictConnection:
    def __init__(self, table):
        self.table = table

    def execute(self, sql, params=None):
        normalized_sql = " ".join(sql.split())
        if normalized_sql.startswith("insert into generation_runs"):
            run_id, run_key = params[:2]
            assert "on conflict (run_key) do nothing" in normalized_sql
            with self.table.lock:
                if run_key in self.table.rows:
                    return Result([])
                self.table.rows[run_key] = run_id
                return Result([{"id": run_id}])
        if normalized_sql.startswith("select id from generation_runs"):
            return Result([{"id": self.table.rows[params[0]]}])
        raise AssertionError(normalized_sql)

    def commit(self):
        pass


def test_two_concurrent_starts_cannot_both_own_daily_key():
    from scotland_facts.config import Settings

    table = SharedRunTable()
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        barrier.wait()
        database = Database(ConflictConnection(table))
        results.append(
            database.start_run("daily:2026-09-06", RunType.DAILY, Settings()).owned
        )

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [False, True]


def test_duplicate_production_run_is_noop_even_if_existing_failed(production_settings):
    from conftest import FakeDatabase

    db = FakeDatabase()
    db.owned = False
    result = run_workflow(production_settings, db=db, now=datetime(2026, 9, 6, tzinfo=ZoneInfo("UTC")))
    assert result.noop is True
    assert result.status == "NOOP"
    assert db.inserted == []
