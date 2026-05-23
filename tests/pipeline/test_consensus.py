"""
tests/pipeline/test_consensus.py — Unit tests for pipeline/consensus.py.
"""

import sqlite3
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from database import dal
from pipeline import consensus


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    dal.initialize_schema(c)
    return c


@pytest.fixture
def mock_smtp():
    return MagicMock()


def test_check_consensus_all_submitted_triggers_intersection(conn, mock_smtp, mocker):
    mock_intersection = mocker.patch("pipeline.intersection.find_valid_slots")
    # Mock returning one valid slot
    from agent.definitions import MeetingSlot
    mock_intersection.return_value = [
        MeetingSlot(utc_start=datetime(2025, 1, 6, 10, tzinfo=timezone.utc), utc_end=datetime(2025, 1, 6, 11, tzinfo=timezone.utc), duration_minutes=60, satisfies_minimum=True)
    ]
    mock_send = mocker.patch("tools.gmail_sender.send_email")

    dal.insert_thread(conn, "t1", "Subject", "a@example.com", "2025-01-01T00:00:00Z")
    dal.insert_participant(conn, "t1", "a@example.com", True)
    dal.insert_participant(conn, "t1", "b@example.com", False)

    windows_json = json.dumps([{"utc_start": "2025-01-06T09:00:00+00:00", "utc_end": "2025-01-06T17:00:00+00:00"}])
    dal.set_availability(conn, "t1", "a@example.com", windows_json, None, "2025-01-01T00:00:00Z")
    dal.set_availability(conn, "t1", "b@example.com", windows_json, None, "2025-01-01T00:00:00Z")

    consensus.check_consensus(conn, mock_smtp, "t1", "2025-01-01T01:00:00Z")

    thread = dal.get_thread(conn, "t1")
    assert thread["status"] == "proposal_sent"
    assert thread["proposed_slot"] is not None

    mock_send.assert_called_once()
    assert mock_intersection.call_count == 1


def test_check_consensus_one_not_submitted_no_action(conn, mock_smtp, mocker):
    mock_intersection = mocker.patch("pipeline.intersection.find_valid_slots")
    dal.insert_thread(conn, "t1", "Subject", "a@example.com", "2025-01-01T00:00:00Z")
    dal.insert_participant(conn, "t1", "a@example.com", True)
    dal.insert_participant(conn, "t1", "b@example.com", False)

    dal.set_availability(conn, "t1", "a@example.com", "[]", None, "2025-01-01T00:00:00Z")
    # b@example.com has not submitted

    consensus.check_consensus(conn, mock_smtp, "t1", "2025-01-01T01:00:00Z")

    thread = dal.get_thread(conn, "t1")
    assert thread["status"] == "awaiting_availability"
    mock_intersection.assert_not_called()


def test_check_consensus_all_confirmed_triggers_provisioning(conn, mock_smtp, mocker):
    dal.insert_thread(conn, "t1", "Subject", "a@example.com", "2025-01-01T00:00:00Z")
    dal.update_thread_status(conn, "t1", "proposal_sent", "2025-01-01T00:00:00Z")
    dal.insert_participant(conn, "t1", "a@example.com", True)
    dal.insert_participant(conn, "t1", "b@example.com", False)

    dal.set_confirmed(conn, "t1", "a@example.com", "2025-01-01T00:00:00Z")
    dal.set_confirmed(conn, "t1", "b@example.com", "2025-01-01T00:00:00Z")

    # In Phase 08 this just hits the TODO stub, so we expect no exceptions and status remains (for now)
    consensus.check_consensus(conn, mock_smtp, "t1", "2025-01-01T01:00:00Z")


def test_check_consensus_one_not_confirmed_no_action(conn, mock_smtp, mocker):
    dal.insert_thread(conn, "t1", "Subject", "a@example.com", "2025-01-01T00:00:00Z")
    dal.update_thread_status(conn, "t1", "proposal_sent", "2025-01-01T00:00:00Z")
    dal.insert_participant(conn, "t1", "a@example.com", True)
    dal.insert_participant(conn, "t1", "b@example.com", False)

    dal.set_confirmed(conn, "t1", "a@example.com", "2025-01-01T00:00:00Z")
    # b not confirmed

    consensus.check_consensus(conn, mock_smtp, "t1", "2025-01-01T01:00:00Z")
    # No action


def test_check_consensus_empty_intersection_resets(conn, mock_smtp, mocker):
    mock_intersection = mocker.patch("pipeline.intersection.find_valid_slots")
    mock_intersection.return_value = []  # No slots
    mock_send = mocker.patch("tools.gmail_sender.send_email")

    dal.insert_thread(conn, "t1", "Subject", "a@example.com", "2025-01-01T00:00:00Z")
    dal.insert_participant(conn, "t1", "a@example.com", True)
    dal.insert_participant(conn, "t1", "b@example.com", False)

    dal.set_availability(conn, "t1", "a@example.com", "[]", None, "2025-01-01T00:00:00Z")
    dal.set_availability(conn, "t1", "b@example.com", "[]", None, "2025-01-01T00:00:00Z")

    consensus.check_consensus(conn, mock_smtp, "t1", "2025-01-01T01:00:00Z")

    thread = dal.get_thread(conn, "t1")
    assert thread["status"] == "awaiting_availability"
    assert thread["proposed_slot"] is None
    
    parts = dal.get_participants(conn, "t1")
    for p in parts:
        assert p["has_submitted_availability"] == 0

    mock_send.assert_called_once()
