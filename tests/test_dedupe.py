from uuid import uuid4

from scotland_facts.dedupe import highest_semantic_match, normalize_fact


def test_same_text_exact_duplicate_key():
    text = "Scotland has hundreds of islands."
    assert normalize_fact(text) == normalize_fact(text)


def test_case_and_punctuation_variant_exact_duplicate_key():
    assert normalize_fact("A SCOTTISH FACT!") == normalize_fact("A Scottish fact.")


def test_similarity_at_threshold_rejected():
    match = uuid4()
    duplicate, matched_id, score = highest_semantic_match([(match, 0.88)], 0.88)
    assert (duplicate, matched_id, score) == (True, match, 0.88)


def test_similarity_below_threshold_accepted():
    duplicate, _, score = highest_semantic_match([(uuid4(), 0.8799)], 0.88)
    assert duplicate is False
    assert score == 0.8799
