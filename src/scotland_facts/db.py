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
from scotland_facts.dedupe import highest_semantic_match
from scotland_facts.fatigue import find_recent_subject
from scotland_facts.models import (
    CATEGORIES,
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

    def require_subscription(self) -> None:
        row = self.conn.execute(
            "select suppressed from subscription_state where id = true"
        ).fetchone()
        if not row or row["suppressed"]:
            raise ValueError("Subscription suppressed or missing; explicit consent renewal required")

    def set_subscription_suppressed(self, suppressed: bool) -> None:
        cursor = self.conn.execute(
            "update subscription_state set suppressed = %s, updated_at = now() where id = true",
            (suppressed,),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise ValueError("Subscription state missing; apply migrations")
        self.conn.commit()

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
            group by category
            """,
        ).fetchall()
        last_used = {row["category"]: row["last_used"] for row in rows}
        return sorted(CATEGORIES, key=lambda category: (category in last_used, last_used.get(category), category))

    def recent_subjects(self, window_days: int) -> list[str]:
        rows = self.conn.execute(
            """
            select subjects from facts
            where generated_at >= now() - (%s * interval '1 day')
            """,
            (window_days,),
        ).fetchall()
        return [subject for row in rows for subject in row["subjects"]]

    def prior_facts(self, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            """
            select fact_text from facts
            order by generated_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()
        return [row["fact_text"] for row in rows]

    def recent_sms(self, limit: int = 10) -> list[str]:
        rows = self.conn.execute(
            """
            select sms_text from facts
            where sms_text is not null
            order by generated_at desc
            limit %s
            """,
            (limit,),
        ).fetchall()
        return [row["sms_text"] for row in rows]

    def exact_duplicate(self, normalized_fact: str) -> UUID | None:
        row = self.conn.execute(
            """
            select id from facts
            where normalized_fact = %s
            order by generated_at desc limit 1
            """,
            (normalized_fact,),
        ).fetchone()
        return row["id"] if row else None

    def nearest_facts(self, embedding: list[float], limit: int = 5) -> list[tuple[UUID, float]]:
        query_vector = Vector(embedding)
        # The + 0 forces an exact distance sort rather than approximate HNSW retrieval.
        rows = self.conn.execute(
            """
            select id, 1 - (embedding <=> %s) as similarity
            from facts
            order by (embedding <=> %s) + 0
            limit %s
            """,
            (query_vector, query_vector, limit),
        ).fetchall()
        return [(row["id"], float(row["similarity"])) for row in rows]

    def record_attempt(self, run_id: UUID, attempt: AttemptRecord, *, commit: bool = True) -> None:
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
        if commit:
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
        *,
        commit: bool = True,
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
        if commit:
            self.conn.commit()
        return fact_id

    def try_accept_fact(
        self, run_id: UUID, record: AttemptRecord, sms_text: str,
        embedding: list[float], status: FactStatus, settings: Settings,
    ) -> UUID | None:
        # End the speculative read transaction. All writers share this short lock;
        # no provider calls or intermediate commits may occur inside it.
        self.conn.commit()
        with self.conn.transaction():
            self.conn.execute("set transaction isolation level read committed")
            self.conn.execute("select pg_advisory_xact_lock(1935896436)")
            repeated = find_recent_subject(
                record.subjects or [], self.recent_subjects(settings.recent_subject_window_days)
            )
            if repeated:
                record.rejection_code = "RECENT_SUBJECT"
                record.rejection_reason = f"Subject claimed by another run: {repeated}"
                return None
            exact = self.exact_duplicate(record.normalized_fact)
            if exact:
                record.matched_fact_id = exact
                record.rejection_code = "EXACT_DUPLICATE"
                record.rejection_reason = "Normalized fact claimed by another run"
                return None
            duplicate, matched_id, similarity = highest_semantic_match(
                self.nearest_facts(embedding), settings.semantic_similarity_threshold
            )
            record.matched_fact_id = matched_id
            record.similarity_score = similarity
            if duplicate:
                record.rejection_code = "SEMANTIC_DUPLICATE"
                record.rejection_reason = f"Similarity {similarity:.4f} meets threshold"
                return None
            fact_id = self.insert_fact(
                run_id, record.candidate_fact, record.normalized_fact, sms_text,
                record.category, record.subjects, record.source_url, record.source_title,
                record.sources, embedding, status, commit=False,
            )
            record.accepted = True
            self.record_attempt(run_id, record, commit=False)
        return fact_id

    def prepare_deliveries(self, fact_id: UUID, slots: tuple[str, ...]) -> list[tuple[UUID, str]]:
        """Commit the complete fan-out before any provider call; never prepare a preview."""
        if not slots or len(set(slots)) != len(slots) or set(slots) - {"primary", "secondary"}:
            raise ValueError("Invalid recipient slots")
        self.conn.commit()
        deliveries = []
        with self.conn.transaction():
            for slot in slots:
                delivery_id = uuid4()
                cursor = self.conn.execute(
                    """
                    insert into sms_deliveries (id, fact_id, recipient_slot, status)
                    select %s, id, %s, 'PENDING' from facts
                    where id = %s and status = 'PENDING' and send_attempted_at is null
                    """, (delivery_id, slot, fact_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("Fact is not eligible for production deliveries")
                deliveries.append((delivery_id, slot))
        return deliveries

    def _sync_primary_fact(self, delivery_id: UUID) -> None:
        # Legacy fact delivery columns describe only the primary recipient.
        # sms_deliveries is authoritative for all sending and reconciliation.
        self.conn.execute(
            """
            update facts f set status = d.status, send_attempted_at = d.send_attempted_at,
                twilio_sid = d.twilio_sid, twilio_status = d.twilio_status,
                twilio_error_code = d.twilio_error_code, sent_at = d.sent_at,
                delivered_at = d.delivered_at
            from sms_deliveries d
            where d.id = %s and d.recipient_slot = 'primary' and f.id = d.fact_id
            """, (delivery_id,),
        )

    def mark_send_attempted(self, fact_id: UUID, recipient_slot: str = "primary") -> None:
        cursor = self.conn.execute(
            """
            update sms_deliveries set status = 'SEND_ATTEMPTED', send_attempted_at = now()
            where id = %s and status = 'PENDING' and send_attempted_at is null
              and recipient_slot = %s
              and exists (select 1 from subscription_state where id = true and not suppressed)
            """,
            (fact_id, recipient_slot),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise RuntimeError("Delivery is not eligible for its one allowed Twilio create attempt")
        self._sync_primary_fact(fact_id)
        self.conn.commit()

    def mark_submitted(self, fact_id: UUID, sid: str, twilio_status: str,
                       app_status: FactStatus, error_code: int | None = None) -> None:
        cursor = self.conn.execute(
            """
            update sms_deliveries set status = %s, twilio_sid = %s, twilio_status = %s,
                twilio_error_code = %s,
                sent_at = case when %s = 'SENT' then now() else sent_at end,
                delivered_at = case when %s = 'DELIVERED' then now() else delivered_at end
            where id = %s and status = 'SEND_ATTEMPTED'
            """,
            (app_status.value, sid, twilio_status, error_code,
             app_status.value, app_status.value, fact_id),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise RuntimeError("Could not persist Twilio response for attempted delivery")
        self._sync_primary_fact(fact_id)
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
            update sms_deliveries set status = %s, twilio_status = %s, twilio_error_code = %s,
                sent_at = case when %s = 'SENT' and sent_at is null then now() else sent_at end,
                delivered_at = case when %s = 'DELIVERED' then now() else delivered_at end
            where id = %s
            """,
            (app_status.value, twilio_status, error_code, app_status.value, app_status.value, fact_id),
        )
        self._sync_primary_fact(fact_id)
        self.conn.commit()

    def mark_definitive_send_failure(self, fact_id: UUID, error_code: int | None) -> None:
        self.conn.execute(
            "update sms_deliveries set status = 'FAILED', twilio_error_code = %s where id = %s",
            (error_code, fact_id),
        )
        self._sync_primary_fact(fact_id)
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

    def reconciliation_candidates(self) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            select id, fact_id, recipient_slot, twilio_sid, status from sms_deliveries
            where (status in ('SUBMITTED', 'SENT') and twilio_sid is not null)
               or status = 'SEND_ATTEMPTED'
            order by created_at
            """,
        ).fetchall()

    def history(self, limit: int) -> list[dict[str, Any]]:
        return self.conn.execute(
            """
            select f.generated_at, f.status, f.category, f.fact_text, f.source_url, f.twilio_status,
                coalesce((select jsonb_agg(jsonb_build_object(
                    'recipient_slot', d.recipient_slot, 'status', d.status,
                    'twilio_status', d.twilio_status, 'twilio_error_code', d.twilio_error_code
                ) order by d.recipient_slot) from sms_deliveries d where d.fact_id = f.id), '[]'::jsonb) as deliveries
            from facts f order by f.generated_at desc limit %s
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
