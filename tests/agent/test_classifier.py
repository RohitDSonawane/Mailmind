"""
tests/agent/test_classifier.py — Unit tests for agent/classifier.py.
"""

from unittest.mock import MagicMock

import pytest

from agent.classifier import classify_intent
from agent.definitions import ClassificationResult


@pytest.fixture
def mock_classifier_run(mocker):
    """Mocks classifier_agent.run_sync to return a dummy result."""
    mock_run = mocker.patch("agent.classifier.classifier_agent.run_sync")
    mock_result = MagicMock()
    mock_result.data = ClassificationResult(
        intent="new_scheduling_request",
        confidence=0.95,
        reasoning="Test reasoning"
    )
    mock_run.return_value = mock_result
    return mock_run


def test_classify_intent_calls_agent_with_correct_args(mock_classifier_run):
    result = classify_intent(
        clean_body="Let's schedule a meeting.",
        thread_status="new"
    )

    # Verify agent was called
    mock_classifier_run.assert_called_once_with(
        user_prompt="Let's schedule a meeting.",
        deps={"thread_status": "new"}
    )

    # Verify result propagates
    assert result.intent == "new_scheduling_request"
    assert result.confidence == 0.95


def test_auto_submitted_header_short_circuits(mock_classifier_run):
    """Auto-Submitted: auto-replied should bypass LLM and return noise."""
    result = classify_intent(
        clean_body="I am out of the office.",
        thread_status="awaiting_availability",
        auto_submitted_header="auto-replied"
    )

    # Verify agent was NOT called
    mock_classifier_run.assert_not_called()

    # Verify deterministic noise result
    assert result.intent == "noise"
    assert result.confidence == 1.0
    assert "Auto-Submitted header present" in result.reasoning


def test_auto_submitted_no_does_not_short_circuit(mock_classifier_run):
    """Auto-Submitted: no is a normal email and should be passed to LLM."""
    result = classify_intent(
        clean_body="Let's schedule a meeting.",
        thread_status="new",
        auto_submitted_header="no"
    )

    # Verify agent WAS called
    mock_classifier_run.assert_called_once()
    assert result.intent == "new_scheduling_request"


def test_auto_submitted_none_does_not_short_circuit(mock_classifier_run):
    """Absence of the header should pass to LLM."""
    result = classify_intent(
        clean_body="Let's schedule a meeting.",
        thread_status="new",
        auto_submitted_header=None
    )

    # Verify agent WAS called
    mock_classifier_run.assert_called_once()
