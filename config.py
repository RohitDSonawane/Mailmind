"""
config.py — Environment variable loading and validation.

Loaded once at import time. Every other module imports typed constants from here.
A missing or invalid variable raises ValueError immediately, preventing the
process from starting in a misconfigured state.
"""

import logging
import os

from dotenv import load_dotenv

# Load .env from the project root (the directory containing this file).
# If .env does not exist, python-dotenv silently does nothing; the validation
# block below will then catch any missing variables.
load_dotenv()

# ---------------------------------------------------------------------------
# Logging bootstrap
# ---------------------------------------------------------------------------
# Configured here so that config-level errors can be logged before any other
# module initialises its own logger.

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require(name: str) -> str:
    """Return the value of an environment variable, raising if missing or empty."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"Required environment variable '{name}' is missing or empty. "
            f"Check your .env file against .env.example."
        )
    return value


def _require_positive_int(name: str) -> int:
    """Return a positive-integer environment variable, raising on bad values."""
    raw = _require(name)
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable '{name}' must be an integer, got: {raw!r}"
        )
    if value <= 0:
        raise ValueError(
            f"Environment variable '{name}' must be a positive integer, got: {value}"
        )
    return value


# ---------------------------------------------------------------------------
# Public typed constants — import these throughout the codebase
# ---------------------------------------------------------------------------

GMAIL_ADDRESS: str = _require("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD: str = _require("GMAIL_APP_PASSWORD")
GROQ_API_KEY: str = _require("GROQ_API_KEY")
MEETING_DURATION_MINUTES: int = _require_positive_int("MEETING_DURATION_MINUTES")
POLL_INTERVAL_SECONDS: int = _require_positive_int("POLL_INTERVAL_SECONDS")
DEFAULT_TIMEZONE: str = _require("DEFAULT_TIMEZONE")

logger.info(
    "Configuration loaded: bot=%s  poll_interval=%ss  meeting_duration=%smin  timezone=%s",
    GMAIL_ADDRESS,
    POLL_INTERVAL_SECONDS,
    MEETING_DURATION_MINUTES,
    DEFAULT_TIMEZONE,
)
