from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


CATEGORIES = (
    "strange_history",
    "folklore",
    "islands",
    "inventions",
    "archaeology",
    "wildlife",
    "castles",
    "engineering",
    "geography",
    "language",
    "food",
    "whisky",
    "famous_scots",
    "traditions",
    "general_history",
)

class RunType(StrEnum):
    DAILY = "DAILY"
    DRY_RUN = "DRY_RUN"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NOOP = "NOOP"


class FactStatus(StrEnum):
    PENDING = "PENDING"
    SEND_ATTEMPTED = "SEND_ATTEMPTED"
    SUBMITTED = "SUBMITTED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DRY_RUN = "DRY_RUN"


class ResearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str
    category: str
    subjects: list[str] = Field(min_length=1, max_length=4)


class StyleSuffix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suffix: str


class Source(BaseModel):
    url: str
    title: str | None = None


class ResearchOutput(BaseModel):
    candidate: ResearchCandidate
    sources: list[Source]
    web_search_performed: bool


class AttemptRecord(BaseModel):
    attempt_number: int
    candidate_fact: str | None = None
    normalized_fact: str | None = None
    category: str | None = None
    subjects: list[str] | None = None
    source_url: str | None = None
    source_title: str | None = None
    sources: list[dict[str, Any]] | None = None
    similarity_score: float | None = None
    matched_fact_id: UUID | str | None = None
    accepted: bool = False
    rejection_code: str | None = None
    rejection_reason: str | None = None


class RunStart(BaseModel):
    id: UUID
    owned: bool
    run_key: str


class WorkflowResult(BaseModel):
    run_id: UUID
    run_key: str
    status: RunStatus
    sms_text: str | None = None
    source_url: str | None = None
    attempts: int = 0
    noop: bool = False
