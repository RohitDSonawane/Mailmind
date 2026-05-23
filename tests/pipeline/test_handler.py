"""
tests/pipeline/test_handler.py — Unit tests for pipeline/handler.py.
"""

import sqlite3
import pytest
from unittest.mock import MagicMock

from database import dal
from pipeline import handler
from tools.gmail_reader import InboundEmail
from agent import classifier
from agent.definitions import ClassificationResult, ExtractorResult, AvailabilityWindow
from datetime import datetime, timezone


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dal.initialize_schema(c)
    return c


@pytest.fixture
def mock_smtp():
    return MagicMock()


def make_email(msg_id, subject, from_addr, to_addrs=None, in_reply=None, refs=None, auto=None, body="Hello"):
    return InboundEmail(
        uid="1",
        message_id=msg_id,
        subject=subject,
        from_address=from_addr,
        to_addresses=to_addrs or ["bot@example.com"],
        cc_addresses=[],
        auto_submitted=auto,
        body_text=body,
        in_reply_to=in_reply,
        references=refs
    )


def test_noise_no_action(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="noise", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)
    
    email = make_email("msg1", "Spam", "spammer@example.com")
    handler.run_pipeline(conn, None, mock_smtp, email, "2025-01-01T00:00:00Z")
    
    assert dal.get_thread(conn, "msg1") is None
    mock_smtp.send_message.assert_not_called()


def test_new_scheduling_request(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="new_scheduling_request", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)

    email = make_email("msg1", "Sync", "a@example.com", ["b@example.com", "bot@example.com"])
    handler.run_pipeline(conn, None, mock_smtp, email, "2025-01-01T00:00:00Z")

    thread = dal.get_thread(conn, "msg1")
    assert thread is not None
    assert thread["status"] == "awaiting_availability"

    parts = dal.get_participants(conn, "msg1")
    emails = {p["email_address"] for p in parts}
    assert "a@example.com" in emails
    assert "b@example.com" in emails
    # Bot might or might not be in depending on config filtering

    # Emails should be sent to participants
    assert mock_smtp.sendmail.call_count >= 1


def test_availability_reply_valid(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="availability_reply", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)
    mock_check = mocker.patch("pipeline.consensus.check_consensus")
    
    mock_extract = ExtractorResult(
        windows=[AvailabilityWindow(utc_start=datetime.now(timezone.utc), utc_end=datetime.now(timezone.utc))],
        inferred_timezone="UTC"
    )
    mocker.patch("agent.extractor.extract_availability", return_value=mock_extract)

    dal.insert_thread(conn, "msg1", "Sync", "a@example.com", "utc")
    dal.insert_participant(conn, "msg1", "a@example.com", True)

    email = make_email("msg2", "Re: Sync", "a@example.com", in_reply="msg1")
    handler.run_pipeline(conn, None, mock_smtp, email, "utc")

    parts = dal.get_participants(conn, "msg1")
    assert parts[0]["has_submitted_availability"] == 1
    mock_check.assert_called_once()


def test_availability_reply_empty_sends_clarification(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="availability_reply", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)
    mock_check = mocker.patch("pipeline.consensus.check_consensus")
    
    from agent.definitions import ExtractorResult
    mock_extract = ExtractorResult(windows=[], inferred_timezone=None)
    mocker.patch("agent.extractor.extract_availability", return_value=mock_extract)

    dal.insert_thread(conn, "msg1", "Sync", "a@example.com", "utc")
    dal.insert_participant(conn, "msg1", "a@example.com", True)

    email = make_email("msg2", "Re: Sync", "a@example.com", in_reply="msg1")
    handler.run_pipeline(conn, None, mock_smtp, email, "utc")

    parts = dal.get_participants(conn, "msg1")
    assert parts[0]["has_submitted_availability"] == 0
    mock_check.assert_not_called()
    mock_smtp.sendmail.assert_called_once()


def test_confirmation(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="confirmation", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)
    mock_check = mocker.patch("pipeline.consensus.check_consensus")

    dal.insert_thread(conn, "msg1", "Sync", "a@example.com", "utc")
    dal.update_thread_status(conn, "msg1", "proposal_sent", "utc")
    dal.insert_participant(conn, "msg1", "a@example.com", True)

    email = make_email("msg2", "Re: Sync", "a@example.com", in_reply="msg1")
    handler.run_pipeline(conn, None, mock_smtp, email, "utc")

    parts = dal.get_participants(conn, "msg1")
    assert parts[0]["has_confirmed"] == 1
    mock_check.assert_called_once()


def test_rejection(conn, mock_smtp, mocker):
    mock_res = ClassificationResult(intent="rejection", confidence=0.9, reasoning="none")
    mocker.patch("agent.classifier.classify_intent", return_value=mock_res)

    dal.insert_thread(conn, "msg1", "Sync", "a@example.com", "utc")
    dal.update_thread_status(conn, "msg1", "proposal_sent", "utc")
    dal.insert_participant(conn, "msg1", "a@example.com", True)
    dal.set_availability(conn, "msg1", "a@example.com", "[{}]", None, "utc")

    email = make_email("msg2", "Re: Sync", "a@example.com", in_reply="msg1")
    handler.run_pipeline(conn, None, mock_smtp, email, "utc")

    thread = dal.get_thread(conn, "msg1")
    assert thread["status"] == "awaiting_availability"
    parts = dal.get_participants(conn, "msg1")
    assert parts[0]["has_submitted_availability"] == 0
    mock_smtp.sendmail.assert_called_once()


def test_duplicate_email(conn, mock_smtp, mocker):
    mock_class = mocker.patch("agent.classifier.classify_intent")
    
    # Mark as processed
    dal.mark_processed(conn, "msg1", "utc")

    email = make_email("msg1", "Sync", "a@example.com")
    handler.run_pipeline(conn, None, mock_smtp, email, "utc")

    mock_class.assert_not_called()
