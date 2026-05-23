"""
tests/pipeline/test_intersection.py — Unit tests for pipeline/intersection.py.
"""

from datetime import datetime, timezone
import pytest

from agent.definitions import AvailabilityWindow
from pipeline.intersection import find_valid_slots


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_two_participants_overlapping_valid_slot():
    windows = {
        "a@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 17))],
        "b@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 13), utc_end=utc(2025, 1, 6, 18))],
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 13)
    assert slots[0].utc_end == utc(2025, 1, 6, 14)
    assert slots[0].duration_minutes == 60


def test_two_participants_no_overlap():
    windows = {
        "a@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 12))],
        "b@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 14), utc_end=utc(2025, 1, 6, 17))],
    }
    slots = find_valid_slots(windows, 60)
    assert slots == []


def test_overlap_exists_but_shorter_than_duration():
    windows = {
        "a@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 13, 30))],
        "b@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 13), utc_end=utc(2025, 1, 6, 17))],
    }
    slots = find_valid_slots(windows, 60)
    assert slots == []


def test_multiple_valid_slots():
    windows = {
        "a@example.com": [
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 11)),
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 14), utc_end=utc(2025, 1, 6, 16))
        ],
        "b@example.com": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 17))],
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 2
    assert slots[0].utc_start == utc(2025, 1, 6, 9)
    assert slots[0].utc_end == utc(2025, 1, 6, 10)
    assert slots[1].utc_start == utc(2025, 1, 6, 14)
    assert slots[1].utc_end == utc(2025, 1, 6, 15)


def test_three_participants_one_limiting():
    windows = {
        "a": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 8), utc_end=utc(2025, 1, 6, 20))],
        "b": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 8), utc_end=utc(2025, 1, 6, 20))],
        "c": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 15), utc_end=utc(2025, 1, 6, 17))],
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 15)


def test_windows_spanning_midnight():
    windows = {
        "a": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 22), utc_end=utc(2025, 1, 7, 2))],
        "b": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 23), utc_end=utc(2025, 1, 7, 4))],
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 23)
    assert slots[0].utc_end == utc(2025, 1, 7, 0)


def test_exactly_equal_window_boundaries():
    windows = {
        "a": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 12))],
        "b": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 12))],
    }
    slots = find_valid_slots(windows, 120)
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 10)
    assert slots[0].utc_end == utc(2025, 1, 6, 12)


def test_single_participant():
    windows = {
        "a": [
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 10)),
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 12), utc_end=utc(2025, 1, 6, 14)),
        ]
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 2
    assert slots[0].utc_start == utc(2025, 1, 6, 9)
    assert slots[1].utc_start == utc(2025, 1, 6, 12)


def test_empty_windows_list_for_one_participant():
    windows = {
        "a": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 10))],
        "b": [],
    }
    slots = find_valid_slots(windows, 60)
    assert slots == []


def test_all_windows_too_short():
    windows = {
        "a": [
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 9, 30)),
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 10, 30)),
        ],
        "b": [
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 9, 30)),
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 10, 30)),
        ]
    }
    slots = find_valid_slots(windows, 60)
    assert slots == []


def test_duplicate_boundary_points():
    windows = {
        "a": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 11))],
        "b": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 11))],
    }
    slots = find_valid_slots(windows, 60)
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 10)


def test_overlapping_windows_for_same_participant():
    windows = {
        "a": [
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 17)),
            AvailabilityWindow(utc_start=utc(2025, 1, 6, 10), utc_end=utc(2025, 1, 6, 18)),
        ],
        "b": [AvailabilityWindow(utc_start=utc(2025, 1, 6, 9), utc_end=utc(2025, 1, 6, 18))],
    }
    slots = find_valid_slots(windows, 60)
    # The merged block should be 09:00 - 18:00
    assert len(slots) == 1
    assert slots[0].utc_start == utc(2025, 1, 6, 9)
    assert slots[0].utc_end == utc(2025, 1, 6, 10)


def test_zero_duration_raises():
    with pytest.raises(ValueError, match="strictly positive"):
        find_valid_slots({"a": []}, 0)
