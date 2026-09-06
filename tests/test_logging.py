from scotland_facts.logging_utils import redact


def test_phone_numbers_are_redacted_to_last_two_digits():
    phone = "+1 " + " ".join(("804", "555", "1234"))
    assert redact(f"delivery failed for {phone}") == "delivery failed for ***34"


def test_database_password_is_redacted():
    password = "redact-me"
    value = redact("".join(("postgresql://service:", password, "@db.example.test/postgres")))
    assert password not in value
    assert "service:***@" in value
