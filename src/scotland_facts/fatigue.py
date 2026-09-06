from __future__ import annotations

import unicodedata
import string

from scotland_facts.dedupe import TRANSLATION


def normalize_subject(subject: str) -> str:
    value = " ".join(
        unicodedata.normalize("NFKC", subject).lower().translate(TRANSLATION).strip().split()
    )
    value = value.strip(string.punctuation)
    return value


def normalize_subjects(subjects: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in subjects:
        value = normalize_subject(raw)
        if not value:
            raise ValueError("Subject tags must normalize to non-empty values")
        if len(value) > 60 or any(not (c.isalnum() or c.isspace() or c in "-'") for c in value):
            raise ValueError(f"Invalid canonical subject tag: {raw!r}")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    if not 1 <= len(normalized) <= 4:
        raise ValueError("Candidates require 1 to 4 distinct subject tags")
    return normalized


def find_recent_subject(candidate_subjects: list[str], recent_subjects: list[str]) -> str | None:
    recent = {normalize_subject(subject) for subject in recent_subjects}
    return next((subject for subject in candidate_subjects if normalize_subject(subject) in recent), None)
