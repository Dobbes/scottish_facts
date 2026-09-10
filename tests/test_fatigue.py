import pytest

from scotland_facts.fatigue import find_recent_subject, normalize_subject, normalize_subjects


def test_exact_normalized_subject_rejected():
    assert find_recent_subject(["edinburgh castle"], ["  Edinburgh Castle!! "]) == "edinburgh castle"


def test_different_subject_accepted():
    assert find_recent_subject(["orkney"], ["edinburgh"]) is None


def test_country_and_category_tags_do_not_block_unrelated_facts():
    assert normalize_subjects(["Scotland", "wildlife", "hen harriers"]) == ["hen harriers"]
    assert find_recent_subject(["scotland", "wildlife", "hen harriers"], ["Scotland", "wildlife", "beavers"]) is None
    assert find_recent_subject(["brough of birsay", "orkney"], ["scotland", "orkney"]) == "orkney"


def test_candidate_needs_a_specific_subject_after_context_filtering():
    with pytest.raises(ValueError, match="specific subject"):
        normalize_subjects(["scotland", "wildlife"])


def test_subject_normalization_and_validation():
    assert normalize_subject("  St. Kilda! ") == "st. kilda"
    with pytest.raises(ValueError, match="Invalid canonical"):
        normalize_subjects(["st. kilda"])
    assert normalize_subjects(["St Kilda", "Outer Hebrides"]) == ["st kilda", "outer hebrides"]


def test_typographic_apostrophe_is_canonicalized():
    assert normalize_subjects(["John O’Groats"]) == ["john o'groats"]


def test_leading_and_trailing_allowed_punctuation_is_stripped():
    assert normalize_subjects(["-'Skye'-"]) == ["skye"]
