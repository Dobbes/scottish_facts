from datetime import datetime, timedelta, timezone

import pytest

from scotland_facts.fatigue import find_recent_subject, normalize_subject, normalize_subjects
from scotland_facts.models import HISTORY_STATUSES


def eligible_subjects(records, now, days=14):
    cutoff = now - timedelta(days=days)
    return [
        subject
        for record in records
        if record["status"] in HISTORY_STATUSES and record["generated_at"] >= cutoff
        for subject in record["subjects"]
    ]


def test_exact_normalized_subject_rejected():
    assert find_recent_subject(["edinburgh castle"], ["  Edinburgh Castle!! "]) == "edinburgh castle"


def test_different_subject_accepted():
    assert find_recent_subject(["orkney"], ["edinburgh"]) is None


@pytest.mark.parametrize("status", ["DRY_RUN", "FAILED"])
def test_dry_run_and_failed_facts_ignored(status):
    now = datetime.now(timezone.utc)
    records = [{"status": status, "generated_at": now, "subjects": ["orkney"]}]
    assert find_recent_subject(["orkney"], eligible_subjects(records, now)) is None


def test_fifteen_day_old_subject_accepted():
    now = datetime.now(timezone.utc)
    records = [
        {"status": "DELIVERED", "generated_at": now - timedelta(days=15), "subjects": ["skye"]}
    ]
    assert find_recent_subject(["skye"], eligible_subjects(records, now)) is None


def test_subject_normalization_and_validation():
    assert normalize_subject("  St. Kilda! ") == "st. kilda"
    with pytest.raises(ValueError, match="Invalid canonical"):
        normalize_subjects(["st. kilda"])
    assert normalize_subjects(["St Kilda", "Outer Hebrides"]) == ["st kilda", "outer hebrides"]


def test_typographic_apostrophe_is_canonicalized():
    assert normalize_subjects(["John O’Groats"]) == ["john o'groats"]


def test_leading_and_trailing_allowed_punctuation_is_stripped():
    assert normalize_subjects(["-'Skye'-"]) == ["skye"]
