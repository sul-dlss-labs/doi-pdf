"""Shared test configuration.

Load a local ``.env`` so tests can pick up ``OPENALEX_API_KEY`` (used to gate
the OpenAlex full-text service tests).
"""

from dotenv import load_dotenv

load_dotenv()
