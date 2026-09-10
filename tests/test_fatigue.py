import pytest

from scotland_facts.fatigue import find_recent_subject, normalize_subject, normalize_subjects


def test_exact_normalized_subject_rejected():
    assert find_recent_subject(["edinburgh castle"], ["  Edinburgh Castle!! "]) == "edinburgh castle"


def test_different_subject_accepted():
    assert find_recent_subject(["orkney"], ["edinburgh"]) is None


def test_subject_normalization_and_validation():
    assert normalize_subject("  St. Kilda! ") == "st. kilda"
    with pytest.raises(ValueError, match="Invalid canonical"):
        normalize_subjects(["st. kilda"])
    assert normalize_subjects(["St Kilda", "Outer Hebrides"]) == ["st kilda", "outer hebrides"]


def test_typographic_apostrophe_is_canonicalized():
    assert normalize_subjects(["John O’Groats"]) == ["john o'groats"]


def test_leading_and_trailing_allowed_punctuation_is_stripped():
    assert normalize_subjects(["-'Skye'-"]) == ["skye"]
