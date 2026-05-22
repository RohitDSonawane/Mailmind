"""
tests/agent/test_extractor.py — Unit tests for agent/extractor.py.
"""

from unittest.mock import MagicMock
from datetime import datetime, timezone

import pytest

from agent.extractor import extract_availability
from agent.definitions import ExtractorResult, AvailabilityWindow


@pytest.fixture
def mock_extractor_run(mocker):
    """Mocks extractor_agent.run_sync to return a dummy result."""
    mock_run = mocker.patch("agent.extractor.extractor_agent.run_sync")
    mock_result = MagicMock()
    mock_result.data = ExtractorResult(
        windows=[
            AvailabilityWindow(
                utc_start=datetime(2025, 1, 7, 14, 0, tzinfo=timezone.utc),
                utc_end=datetime(2025, 1, 7, 16, 0, tzinfo=timezone.utc)
            )
        ],
        inferred_timezone="America/New_York"
    )
    mock_run.return_value = mock_result
    return mock_run


def test_extract_availability_calls_agent_with_correct_args(mock_extractor_run):
    current_utc = "2025-01-06T10:00:00Z"
    result = extract_availability(
        clean_body="I'm free tomorrow 9am-11am EST.",
        current_utc=current_utc,
        participant_timezone="America/New_York"
    )

    # Verify agent was called with correct text and dependencies
    mock_extractor_run.assert_called_once_with(
        user_prompt="I'm free tomorrow 9am-11am EST.",
        deps={
            "current_utc": current_utc,
            "participant_timezone": "America/New_York"
        }
    )

    # Verify result propagates
    assert len(result.windows) == 1
    assert result.inferred_timezone == "America/New_York"


def test_extract_availability_handles_none_timezone(mock_extractor_run):
    """If no timezone is known, 'None' string should be passed to prompt context."""
    current_utc = "2025-01-06T10:00:00Z"
    extract_availability(
        clean_body="I'm free tomorrow 9am-11am EST.",
        current_utc=current_utc,
        participant_timezone=None
    )

    mock_extractor_run.assert_called_once_with(
        user_prompt="I'm free tomorrow 9am-11am EST.",
        deps={
            "current_utc": current_utc,
            "participant_timezone": "None"
        }
    )
