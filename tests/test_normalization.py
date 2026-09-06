from scotland_facts.dedupe import normalize_fact


def test_punctuation_case_and_quote_normalization():
    assert normalize_fact("Scotland's national animal is the unicorn.") == normalize_fact(
        "SCOTLAND’S NATIONAL ANIMAL IS THE UNICORN!"
    )


def test_whitespace_collapse():
    assert normalize_fact("  A\tScottish\n fact. ") == "a scottish fact"


def test_apostrophe_inside_word_is_preserved_only_inside_word():
    assert normalize_fact("'Scotland' isn't -- tiny") == "scotland isn't tiny"
