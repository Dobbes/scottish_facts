import pytest

from scotland_facts.style import STYLE_PROMPT, StyleValidationError, build_sms, validate_suffix


FACT = "Scotland's national animal is the unicorn."


def test_style_prompt_states_numeric_suffix_limit():
    assert "at most 90 Unicode characters" in STYLE_PROMPT


def test_style_interface_returns_suffix_and_preserves_fact():
    suffix = validate_suffix("Your compulsory education resumes tomorrow.", 90)
    sms = build_sms(FACT, suffix, 300)
    assert sms == f"SCOTLAND FACTS: {FACT} {suffix}"


def test_suffix_max_length_enforced():
    with pytest.raises(StyleValidationError, match="1-5"):
        validate_suffix("123456", 5)


def test_final_message_max_length_enforced():
    with pytest.raises(StyleValidationError, match="exceeds"):
        build_sms(FACT, "A" * 90, 50)


@pytest.mark.parametrize(
    "suffix,reason",
    [
        ("Visit https://example.com now.", "URL"),
        ("A unicorn approves 🦄.", "emoji"),
        ("Line one.\nLine two.", "one line"),
        ("Reply STOP for fewer bagpipes.", "control command"),
        ("Reply HELP for tartan assistance.", "control command"),
        ("Reply: STOP for fewer bagpipes.", "control command"),
        ('Reply "HELP" for tartan assistance.', "control command"),
        ("Text unsubscribe to escape.", "control command"),
    ],
)
def test_unsafe_suffix_rejected(suffix, reason):
    with pytest.raises(StyleValidationError, match=reason):
        validate_suffix(suffix, 90)


def test_harmless_fake_command_accepted():
    assert validate_suffix("Reply HAGGIS to receive absolutely nothing.", 90)


def test_reserved_words_in_ordinary_prose_are_not_globally_banned():
    assert validate_suffix("The lessons never stop, apparently.", 90)
