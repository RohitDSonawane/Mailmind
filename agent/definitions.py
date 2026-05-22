"""
agent/definitions.py — Shared types and Pydantic schemas for the agent layer.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Classifier Output Schema
# ---------------------------------------------------------------------------

IntentLiteral = Literal[
    "new_scheduling_request",
    "availability_reply",
    "confirmation",
    "rejection",
    "noise",
]


class ClassificationResult(BaseModel):
    """Output schema for the intent classifier agent."""
    intent: IntentLiteral = Field(
        ...,
        description="The primary intent of the email."
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0."
    )
    reasoning: str = Field(
        ...,
        description="One sentence explaining why this intent was chosen."
    )


# ---------------------------------------------------------------------------
# Extractor Output Schema
# ---------------------------------------------------------------------------

class AvailabilityWindow(BaseModel):
    """A contiguous block of time a participant is available."""
    utc_start: datetime = Field(
        ...,
        description="Start time of the availability window, strictly in UTC."
    )
    utc_end: datetime = Field(
        ...,
        description="End time of the availability window, strictly in UTC. Must be strictly after utc_start."
    )


class ExtractorResult(BaseModel):
    """Output schema for the availability extractor agent."""
    windows: list[AvailabilityWindow] = Field(
        default_factory=list,
        description="List of extracted availability windows. Empty if the user was ambiguous or did not provide concrete times."
    )
    inferred_timezone: str | None = Field(
        default=None,
        description="The IANA timezone string inferred from the user's reply (e.g. 'America/New_York'). Null if none specified."
    )


# ---------------------------------------------------------------------------
# Internal System Types
# ---------------------------------------------------------------------------

class MeetingSlot(BaseModel):
    """A fully validated meeting slot resulting from the intersection algorithm."""
    utc_start: datetime
    utc_end: datetime
    duration_minutes: int
    satisfies_minimum: bool = True
