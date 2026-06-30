"""Shared HTTP configuration."""

from __future__ import annotations

import platform
import re

# A descriptive User-Agent gets us into the OpenAlex / CrossRef "polite" pools
# and avoids being treated as an anonymous bot by publishers.
USER_AGENT = "doi-pdf/0.0.1 (https://github.com/sul-dlss-labs/doi-pdf; mailto:rialto-service@lists.stanford.edu)"

# Chrome major version advertised by the headless-browser fallback. Modern
# Chrome "reduces" its UA to ``Chrome/<major>.0.0.0``, so the major plus the OS
# token below are the only parts a server actually sees -- keep this roughly
# current so the string is not conspicuously old.
_CHROME_MAJOR = 131


def _platform_tokens() -> tuple[str, str]:
    """Return ``(UA platform token, Sec-CH-UA-Platform value)`` for the host OS.

    The browser we drive reports the *host* OS through ``navigator.platform``
    and the ``Sec-CH-UA-Platform`` client hint, so the User-Agent we present has
    to name the same OS. A macOS UA served from a Linux box is a contradiction
    that bot-protection fingerprinting looks for specifically.
    """
    system = platform.system()
    if system == "Darwin":
        return "Macintosh; Intel Mac OS X 10_15_7", "macOS"
    if system == "Windows":
        return "Windows NT 10.0; Win64; x64", "Windows"
    return "X11; Linux x86_64", "Linux"


_UA_PLATFORM, BROWSER_PLATFORM = _platform_tokens()

# Publisher and repository web servers often refuse the descriptive UA above,
# so the headless browser presents an ordinary Chrome UA -- matched to the host
# OS so it doesn't contradict the browser's own client hints.
BROWSER_USER_AGENT = (
    f"Mozilla/5.0 ({_UA_PLATFORM}) "
    f"AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROME_MAJOR}.0.0.0 Safari/537.36"
)

# Low-entropy client-hint headers consistent with BROWSER_USER_AGENT. Sending
# these keeps the UA string and the Sec-CH-UA hints from disagreeing, which is
# itself a tell when they do.
BROWSER_CLIENT_HINTS = {
    "sec-ch-ua": (
        f'"Chromium";v="{_CHROME_MAJOR}", "Google Chrome";v="{_CHROME_MAJOR}", "Not_A Brand";v="24"'
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": f'"{BROWSER_PLATFORM}"',
}

DEFAULT_TIMEOUT = 30

_SECRET_PARAM_RE = re.compile(r"(api_key=)[^&\s]+")


def redact(url: str) -> str:
    """Mask an ``api_key`` query parameter so secrets stay out of logs."""
    return _SECRET_PARAM_RE.sub(r"\1***", url)
