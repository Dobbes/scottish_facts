from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scotland_facts.config import Settings
from scotland_facts.models import (
    CATEGORIES,
    HISTORY_STATUSES,
    AttemptRecord,
    FactStatus,
    RunStart,
    RunStatus,
    RunType,
)


def connect_database(database_url: str) -> psycopg.Connection[Any]:
    conn = psycopg.connect(database_url, row_factory=dict_row)
    conn.execute("set search_path to public, extensions")
    register_vector(conn)
    return conn


class Database:
    def __init__(self, conn: Any):
        self.conn = conn

    @classmethod
    def connect(cls, settings: Settings) -> "Database":
        return cls(connect_database(settings.secret("supabase_db_url")))

    def close(self) -> None:
        self.conn.close()

    def rollback(self) -> None:
        self.conn.rollback()

    def start_run(self, run_key: str, run_type: RunType, settings: Settings) -> RunStart:
        run_id = uuid4()
        row = self.conn.execute(
            """
            insert into generation_runs (
                id, run_key, run_type, status, research_model, style_model,
                embedding_model, dry_run
            ) values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_key) do nothing
            returning id
            """,
            (
                run_id,
                run_key,
                run_type.value,
                RunStatus.RUNNING.value,
                settings.research_model,
                settings.style_model,
                settings.embedding_model,
                run_type == RunType.DRY_RUN,
            ),
        ).fetchone()
        self.conn.commit()
        if row:
            return RunStart(id=row["id"], owned=True, run_key=run_key)
        existing = self.conn.execute(
            "select id from generation_runs where run_key = %s", (run_key,)
        ).fetchone()
        if not existing:
            raise RuntimeError("Run key conflict occurred but existing run could not be read")
        return RunStart(id=existing["id"], owned=False, run_key=run_key)

    def category_order(self) -> list[str]:
        rows = self.conn.execute(
            """
            select category, max(generated_at) as last_used
            from facts
            where status = any(%s)
            group by category
            """,
            (list(HISTORY_STATUSES),),
        ).fetchall()
        last_used = {row["category"]: row["last_used"] for row in rows}
        return sorted(CATEGORIES, key=lambda category: (category in last_used, last_used.get(category), category))

    def recent_subjects(self, window_days: int) -> list[str]:
        rows = self.conn.execute(
            """
            select subjects from facts
            where status = any(%s)
              and generated_at >= now() - (%s * interval '1 day')
            """,
            (list(HISTORY_STATUSES), window_days),
        ).fetchall()
        return [subject for row in rows for subject in row["subjects"]]

    def prior_facts(self, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            """
            select fact_text from facts
            where status = any(%s)
            order by generated_at desc
            limit %s
            """,
            (list(HISTORY_STATUSES), limit),
        ).fetchall()
        return [row["fact_text"] for row in rows]

    def recent_sms(self, limit: int = 10) -> list[str]:
        rows = self.conn.execute(
            """
            select sms_text from facts
            where status = any(%s) and sms_text is not null
            order by generated_at desc
            limit %s
            """,
            (list(HISTORY_STATUSES), limit),
        ).fetchall()
        return [row["sms_text"] for row in rows]

    def exact_duplicate(self, normalized_fact: str) -> UUID | None:
        row = self.conn.execute(
            """
            select id from facts
            where normalized_fact = %s and status = any(%s)
            order by generated_at desc limit 1
            """,
            (normalized_fact, list(HISTORY_STATUSES)),
        ).fetchone()
        return row["id"] if row else None

    def nearest_facts(self, embedding: list[float], limit: int = 5) -> list[tuple[UUID, float]]:
        query_vector = Vector(embedding)
        rows = self.conn.execute(
            """
            select id, 1 - (embedding <=> %s) as similarity
            from facts
            where status = any(%s)
            order by embedding <=> %s
            limit %s
            """,
            (query_vector, list(HISTORY_STATUSES), query_vector, limit),
        ).fetchall()
        return [(row["id"], float(row["similarity"])) for row in rows]

    def record_attempt(self, run_id: UUID, attempt: AttemptRecord) -> None:
        self.conn.execute(
            """
            insert into generation_attempts (
                id, run_id, attempt_number, candidate_fact, normalized_fact,
                category, subjects, source_url, source_title, sources,
                similarity_score, matched_fact_id, accepted, rejection_code,
                rejection_reason
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
                run_id,
                attempt.attempt_number,
                attempt.candidate_fact,
                attempt.normalized_fact,
                attempt.category,
                attempt.subjects,
                attempt.source_url,
                attempt.source_title,
                Jsonb(attempt.sources) if attempt.sources is not None else None,
                attempt.similarity_score,
                attempt.matched_fact_id,
                attempt.accepted,
                attempt.rejection_code,
                attempt.rejection_reason,
            ),
        )
        self.conn.execute(
            "update generation_runs set attempts = greatest(attempts, %s) where id = %s",
            (attempt.attempt_number, run_id),
        )
        self.conn.commit()

    def insert_fact(
        self,
        run_id: UUID,
        fact_text: str,
        normalized_fact: str,
        sms_text: str,
        category: str,
        subjects: list[str],
        source_url: str,
        source_title: str | None,
        sources: list[dict[str, Any]],
        embedding: list[float],
        status: FactStatus,
    ) -> UUID:
        fact_id = uuid4()
        self.conn.execute(
            """
            insert into facts (
                id, run_id, fact_text, normalized_fact, sms_text, category,
                subjects, source_url, source_title, sources, embedding, status
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                fact_id,
                run_id,
                fact_text,
                normalized_fact,
                sms_text,
                category,
                subjects,
                source_url,
                source_title,
                Jsonb(sources),
                Vector(embedding),
                status.value,
            ),
        )
        self.conn.commit()
        return fact_id

    def mark_send_attempted(self, fact_id: UUID) -> None:
        cursor = self.conn.execute(
            """
            update facts set status = 'SEND_ATTEMPTED', send_attempted_at = now()
            where id = %s and status = 'PENDING' and send_attempted_at is null
            """,
            (fact_id,),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise RuntimeError("Fact is not eligible for its one allowed Twilio create attempt")
        self.conn.commit()

    def mark_submitted(self, fact_id: UUID, sid: str, twilio_status: str | None) -> None:
        self.conn.execute(
            """
            update facts set status = 'SUBMITTED', twilio_sid = %s, twilio_status = %s
            where id = %s and status = 'SEND_ATTEMPTED'
            """,
            (sid, twilio_status, fact_id),
        )
        self.conn.commit()

    def update_twilio_status(
        self,
        fact_id: UUID,
        app_status: FactStatus,
        twilio_status: str,
        error_code: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            update facts set status = %s, twilio_status = %s, twilio_error_code = %s,
                sent_at = case when %s = 'SENT' and sent_at is null then now() else sent_at end,
                delivered_at = case when %s = 'DELIVERED' then now() else delivered_at end
            where id = %s
            """,
            (app_status.value, twilio_status, error_code, app_status.value, app_status.value, fact_id),
        )
        self.conn.commit()

    def mark_definitive_send_failure(self, fact_id: UUID, error_code: int | None) -> None:
        self.conn.execute(
            "update facts set status = 'FAILED', twilio_error_code = %s where id = %s",
            (error_code, fact_id),
        )
        self.conn.commit()

    def complete_run(self, run_id: UUID, status: RunStatus = RunStatus.SUCCEEDED) -> None:
        self.conn.execute(
            "update generation_runs set status = %s, completed_at = now() where id = %s",
            (status.value, run_id),
        )
        self.conn.commit()

    def fail_run(self, run_id: UUID, code: str, reason: str) -> None:
        self.conn.execute(
            """
            update generation_runs
            set status = 'FAILED', completed_at = now(), failure_code = %s, failure_reason = %s
            where id = %s
            """,
            (code, reason[:1000], run_id),
        )
        self.conn.commit()

    def reconciliation_candidates(self, days: int = 7) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            select id, twilio_sid, status from facts
            where status in ('SUBMITTED', 'SENT') and twilio_sid is not null
              and generated_at >= now() - (%s * interval '1 day')
            """,
            (days,),
        ).fetchall()

    def history(self, limit: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            select generated_at, status, category, fact_text, source_url, twilio_status
            from facts order by generated_at desc limit %s
            """,
            (limit,),
        ).fetchall()

    def doctor_schema(self) -> dict[str, Any]:
        self.conn.execute("select 1").fetchone()
        vector = self.conn.execute(
            "select 1 from pg_extension where extname = 'vector'"
        ).fetchone()
        rows = self.conn.execute(
            """
            select table_name from information_schema.tables
            where table_schema = 'public'
              and table_name = any(%s)
            """,
            (["generation_runs", "facts", "generation_attempts", "schema_migrations"],),
        ).fetchall()
        return {"vector": bool(vector), "tables": sorted(row["table_name"] for row in rows)}
