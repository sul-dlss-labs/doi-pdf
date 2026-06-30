"""Shared HTTP configuration."""

from __future__ import annotations

import re

# A descriptive User-Agent gets us into the OpenAlex / CrossRef "polite" pools
# and avoids being treated as an anonymous bot by publishers.
USER_AGENT = "doi-pdf/0.0.1 (https://github.com/sul-dlss-labs/doi-pdf; mailto:rialto-service@lists.stanford.edu)"

# Publisher and repository web servers often refuse the descriptive UA above,
# so the headless browser presents an ordinary Chrome UA instead.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30

_SECRET_PARAM_RE = re.compile(r"(api_key=)[^&\s]+")


def redact(url: str) -> str:
    """Mask an ``api_key`` query parameter so secrets stay out of logs."""
    return _SECRET_PARAM_RE.sub(r"\1***", url)
