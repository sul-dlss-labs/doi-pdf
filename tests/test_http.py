"""Tests for secret redaction in logged URLs (no network)."""

import platform

from doi_pdf._http import (
    BROWSER_CLIENT_HINTS,
    BROWSER_PLATFORM,
    BROWSER_USER_AGENT,
    redact,
)


def test_redact_masks_api_key() -> None:
    url = "https://content.openalex.org/works/W1.pdf?api_key=supersecret"
    assert redact(url) == "https://content.openalex.org/works/W1.pdf?api_key=***"


def test_redact_masks_api_key_among_other_params() -> None:
    assert redact("https://x/y?a=1&api_key=secret&b=2") == "https://x/y?a=1&api_key=***&b=2"


def test_redact_leaves_urls_without_api_key_untouched() -> None:
    url = "https://journals.plos.org/plosone/article/file?id=10.1371/x&type=printable"
    assert redact(url) == url


def test_browser_user_agent_names_the_host_os() -> None:
    """The spoofed UA must match the host OS, or it contradicts the browser."""
    expected_token = {
        "Darwin": "Macintosh",
        "Windows": "Windows NT",
        "Linux": "X11; Linux",
    }.get(platform.system(), "X11; Linux")
    assert expected_token in BROWSER_USER_AGENT
    assert "Headless" not in BROWSER_USER_AGENT


def test_browser_client_hints_agree_with_user_agent() -> None:
    """Sec-CH-UA-Platform must match the UA's OS, and the brand major the UA's."""
    assert BROWSER_CLIENT_HINTS["sec-ch-ua-platform"] == f'"{BROWSER_PLATFORM}"'
    # The Chrome major in the UA (Chrome/131.0.0.0) appears in the brand list.
    major = BROWSER_USER_AGENT.split("Chrome/")[1].split(".")[0]
    assert f'"Google Chrome";v="{major}"' in BROWSER_CLIENT_HINTS["sec-ch-ua"]
