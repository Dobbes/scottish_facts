import pytest

from scotland_facts.style import SMS_FOOTER, SAFE_SUFFIXES, STYLE_PROMPT, StyleValidationError, build_sms, validate_suffix


FACT = "Scotland's national animal is the unicorn."


def test_style_prompt_states_numeric_suffix_limit():
    assert "at most 90 Unicode characters" in STYLE_PROMPT


def test_style_brief_requires_detail_specific_callbacks():
    assert "swap test" in STYLE_PROMPT
    assert "absent from the fact" in STYLE_PROMPT


def test_style_interface_returns_suffix_and_preserves_fact():
    suffix = validate_suffix("Your compulsory education resumes tomorrow.", 90)
    sms = build_sms(FACT, suffix, 300)
    assert sms == f"SCOTLAND FACTS: {FACT} {suffix} {SMS_FOOTER}"


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


def test_fake_command_rejected():
    with pytest.raises(StyleValidationError):
        validate_suffix("Reply HAGGIS to receive absolutely nothing.", 90)


def test_reserved_words_in_ordinary_prose_are_not_globally_banned():
    assert validate_suffix("The lessons never stop, apparently.", 90)


@pytest.mark.parametrize("fact", [
    "The Declaration of Arbroath is a medieval Latin text.",
    "Scottish universities send researchers around the world.",
    "The letter was a reply to the king.",
    "Mountain rescue teams respond to emergencies in Scotland.",
])
def test_ordinary_prose_is_not_a_control_command(fact):
    assert build_sms(fact, SAFE_SUFFIXES[0], 300) == f"SCOTLAND FACTS: {fact} {SAFE_SUFFIXES[0]} {SMS_FOOTER}"


@pytest.mark.parametrize("instruction", [
    "Reply STOP to leave.", 'Text "HELP" for assistance.',
    "Respond with STOP.", "Send the word CANCEL.",
])
def test_final_message_still_rejects_control_instructions(instruction):
    with pytest.raises(StyleValidationError, match="control command"):
        build_sms(instruction, SAFE_SUFFIXES[0], 300)


def test_footer_is_not_a_valid_generated_suffix():
    with pytest.raises(StyleValidationError, match="control command"):
        validate_suffix(SMS_FOOTER, 90)


def test_complete_sms_exact_boundary_and_hard_cap():
    suffix = SAFE_SUFFIXES[0]
    overhead = len(build_sms("", suffix, 300))
    sms = build_sms("F" * (300 - overhead), suffix, 300)
    assert len(sms) == 300
    assert sms.endswith(SMS_FOOTER)
    assert sms.count(SMS_FOOTER) == 1
    with pytest.raises(StyleValidationError, match="exceeds 300"):
        build_sms("F" * (301 - overhead), suffix, 999)


def test_request_suffix_reserves_footer_budget(base_settings):
    import json
    from types import SimpleNamespace
    from scotland_facts.style import request_suffix

    payloads = []

    def create(**kwargs):
        payloads.append(json.loads(kwargs["input"][1]["content"]))
        assert kwargs["reasoning"] == {"effort": "medium"}
        assert kwargs["text"]["format"]["schema"]["properties"]["suffix"]["enum"] == payloads[-1]["allowed_suffixes"]
        return SimpleNamespace(output_text=json.dumps({"suffix": SAFE_SUFFIXES[1]}))

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    settings = base_settings.model_copy(update={"sms_max_chars": 260})
    request_suffix(client, settings, "F" * 180, [])
    payload = payloads[0]
    assert payload["allowed_suffixes"]
    assert len(payload["allowed_suffixes"]) < len(SAFE_SUFFIXES)
    for suffix in payload["allowed_suffixes"]:
        assert len(suffix) <= payload["maximum_suffix_characters"]
        assert len(build_sms("F" * 180, suffix, 260)) <= 260
    with pytest.raises(StyleValidationError, match="No reviewed suffix fits"):
        request_suffix(client, settings.model_copy(update={"sms_max_chars": 20}), FACT, [])
    assert len(payloads) == 1


@pytest.mark.parametrize("exhausted", [False, True])
def test_request_suffix_avoids_recent_endings_with_budget_fallback(base_settings, exhausted):
    import json
    from types import SimpleNamespace
    from scotland_facts.style import request_suffix

    budget = 45
    fitting = [suffix for suffix in SAFE_SUFFIXES if len(suffix) <= budget]
    recent_suffixes = fitting if exhausted else fitting[:1]
    assert len(recent_suffixes) <= 10
    recent_sms = [build_sms(FACT, suffix, 300) for suffix in recent_suffixes]
    expected = fitting if exhausted else fitting[1:]

    def create(**kwargs):
        payload = json.loads(kwargs["input"][1]["content"])
        assert payload["allowed_suffixes"] == expected
        assert kwargs["text"]["format"]["schema"]["properties"]["suffix"]["enum"] == expected
        return SimpleNamespace(output_text=json.dumps({"suffix": expected[0]}))

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    settings = base_settings.model_copy(update={"style_suffix_max_chars": budget})
    assert request_suffix(client, settings, FACT, recent_sms) == expected[0]
