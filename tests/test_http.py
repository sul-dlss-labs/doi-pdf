"""Tests for secret redaction in logged URLs (no network)."""

from doi_pdf._http import redact


def test_redact_masks_api_key() -> None:
    url = "https://content.openalex.org/works/W1.pdf?api_key=supersecret"
    assert redact(url) == "https://content.openalex.org/works/W1.pdf?api_key=***"


def test_redact_masks_api_key_among_other_params() -> None:
    assert redact("https://x/y?a=1&api_key=secret&b=2") == "https://x/y?a=1&api_key=***&b=2"


def test_redact_leaves_urls_without_api_key_untouched() -> None:
    url = "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=printable"
    assert redact(url) == url
