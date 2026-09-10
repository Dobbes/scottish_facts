from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest

from scotland_facts.style import SAFE_SUFFIXES, SMS_FOOTER, build_sms, validate_suffix


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = [DOCS / name for name in (
    "index.html", "privacy/index.html", "terms/index.html", "enrollment/index.html",
)]
SUPPORT = "mailto:brunslx@gmail.com"


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


@pytest.mark.parametrize("path", PAGES, ids=lambda path: str(path.relative_to(DOCS)))
def test_static_pages_accessibility_links_and_no_collection(path):
    page = Page(path)
    assert ("html", {"lang": "en"}) in page.tags
    assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in page.tags)
    assert sum(tag == "h1" for tag, _ in page.tags) == 1
    assert sum(tag == "main" for tag, _ in page.tags) == 1
    assert any(tag == "nav" and attrs.get("aria-label") for tag, attrs in page.tags)
    assert any(tag == "a" and attrs.get("href") == "#main" for tag, attrs in page.tags)
    assert not {"script", "form", "input", "iframe", "img"} & {tag for tag, _ in page.tags}
    links = [attrs["href"] for _, attrs in page.tags if "href" in attrs]
    assert SUPPORT in links
    assert "Scotland Facts is operated by Elumsden Sole." in " ".join(page.text)
    assert "https://github.com/Dobbes/scottish_facts/issues" not in links
    assert "do not post personal information" in " ".join(page.text).lower()
    for href in links:
        url = urlsplit(href)
        if url.scheme:
            assert url.scheme == "https" or href == SUPPORT
            continue
        assert not url.netloc and not url.path.startswith("/")
        target = (path.parent / url.path).resolve() if url.path else path
        if target.is_dir():
            target /= "index.html"
        assert target.is_relative_to(DOCS)
        assert target.is_file(), (path, href)
        if url.fragment:
            assert any(attrs.get("id") == url.fragment for _, attrs in Page(target).tags)


def test_public_policy_and_enrollment_disclosures():
    privacy = " ".join(Page(DOCS / "privacy/index.html").text).lower()
    for phrase in ("marketing or promotional", "opt-in data and consent", "service providers",
                   "no inbound webhook", "not automatic or instantaneous", "no automatic retention expiry",
                   "provider retention", "private consent", "phone-free"):
        assert phrase in privacy
    terms = " ".join(Page(DOCS / "terms/index.html").text).lower()
    for phrase in ("message and data rates may apply", "up to one fact sms per day",
                   "not a condition of purchase", "carriers are not liable", "fresh affirmative consent",
                   "stop", "help", "start or unstop"):
        assert phrase in terms
    enrollment = " ".join(Page(DOCS / "enrollment/index.html").text).lower()
    for phrase in ("verbal consent script", "unambiguous affirmative answer", "no enrollment keyword",
                   "outside this repository", "does not automatically send enrollment confirmations",
                   "disclosure version", "timezone", "affirmatively agree"):
        assert phrase in enrollment
    assert (DOCS / ".nojekyll").is_file()


def test_documented_daily_samples_use_actual_validated_suffixes():
    texts = [path.read_text(encoding="utf-8") for path in PAGES]
    texts.extend((ROOT / name).read_text(encoding="utf-8") for name in ("README.md", "guides/RESUBMISSION.md"))
    samples = re.findall(
        r'(?:^|<p class="sample">)(SCOTLAND FACTS: [^\n<>]+Reply STOP to opt out\.)',
        "\n".join(texts), re.MULTILINE,
    )
    assert len(samples) >= 4
    for sample in samples:
        body = sample.removeprefix("SCOTLAND FACTS: ").removesuffix(f" {SMS_FOOTER}")
        suffix = next(suffix for suffix in SAFE_SUFFIXES if body.endswith(f" {suffix}"))
        fact = body.removesuffix(f" {suffix}")
        assert validate_suffix(suffix, 90) == suffix
        assert build_sms(fact, suffix, 300) == sample


def test_service_templates_and_operator_documentation():
    guide = (ROOT / "guides/RESUBMISSION.md").read_text(encoding="utf-8")
    templates = re.findall(r"```text\n(.*?)\n```", guide, re.DOTALL)
    assert len(templates) == 6
    for template in templates:
        assert len(template) <= 300
        assert "\n" not in template
    for route in ("privacy/", "terms/", "enrollment/"):
        assert f"https://dobbes.github.io/scottish_facts/{route}" in guide
    for phrase in ("Not implemented in the application", "ATTEMPTED", "do not click again",
                   "Elumsden Sole", "brunslx@gmail.com"):
        assert phrase in guide
    assert "https://github.com/Dobbes/scottish_facts/issues" not in guide
    for template in (templates[2], templates[4], templates[5]):
        assert "brunslx@gmail.com" in template
    for name in ("README.md", "guides/USER_SETUP.md", "guides/CLI_SPEC.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "Scotland Facts is operated by Elumsden Sole" in text
        assert "brunslx@gmail.com" in text
