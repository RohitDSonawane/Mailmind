"""
pipeline/intersection.py — Slot Intersection Algorithm.

Pure-Python implementation for finding valid meeting slots given a set of
participant availability windows. All datetimes must be UTC-aware.
"""

from datetime import datetime, timedelta
from typing import Dict, List

from agent.definitions import AvailabilityWindow, MeetingSlot


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _collect_boundaries(windows_by_participant: Dict[str, List[AvailabilityWindow]]) -> List[datetime]:
    """Collect all unique start and end times from all windows."""
    boundaries = set()
    for windows in windows_by_participant.values():
        for w in windows:
            boundaries.add(w.utc_start)
            boundaries.add(w.utc_end)
    return sorted(list(boundaries))


def _participant_available_during(windows: List[AvailabilityWindow], t_start: datetime, t_end: datetime) -> bool:
    """
    Check if a participant is available for the entire interval [t_start, t_end].
    They are available if at least one window completely contains the interval.
    """
    for w in windows:
        if w.utc_start <= t_start and w.utc_end >= t_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_valid_slots(
    windows_by_participant: Dict[str, List[AvailabilityWindow]],
    duration_minutes: int
) -> List[MeetingSlot]:
    """
    Find all valid meeting slots that work for all participants.

    Parameters
    ----------
    windows_by_participant : Dict[str, List[AvailabilityWindow]]
        A dictionary mapping participant emails to their availability windows.
    duration_minutes : int
        The minimum required duration for the meeting in minutes.

    Returns
    -------
    List[MeetingSlot]
        A chronologically sorted list of valid meeting slots.

    Raises
    ------
    ValueError
        If duration_minutes is 0 or negative.
    """
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be strictly positive.")

    if not windows_by_participant:
        return []

    # Step 1: Collect boundaries
    boundaries = _collect_boundaries(windows_by_participant)
    if not boundaries:
        return []

    req_duration = timedelta(minutes=duration_minutes)
    valid_intervals = []

    # Step 2: Evaluate each interval
    for i in range(len(boundaries) - 1):
        t_start = boundaries[i]
        t_end = boundaries[i + 1]

        # Skip intervals that are too short to fit the meeting
        if (t_end - t_start) < req_duration:
            continue

        # Check if all participants are available
        all_available = True
        for participant_windows in windows_by_participant.values():
            if not participant_windows:
                # If any participant has no windows, no overlap is possible at all
                all_available = False
                break
            if not _participant_available_during(participant_windows, t_start, t_end):
                all_available = False
                break

        if all_available:
            valid_intervals.append((t_start, t_end))

    if not valid_intervals:
        return []

    # Step 3: Merge adjacent valid intervals
    merged_blocks = []
    current_start, current_end = valid_intervals[0]

    for i in range(1, len(valid_intervals)):
        next_start, next_end = valid_intervals[i]
        if next_start == current_end:
            # Adjacent, extend the current block
            current_end = next_end
        else:
            # Not adjacent, save the current block and start a new one
            merged_blocks.append((current_start, current_end))
            current_start, current_end = next_start, next_end

    # Save the last block
    merged_blocks.append((current_start, current_end))

    # Step 4: Generate MeetingSlot objects
    slots = []
    for block_start, block_end in merged_blocks:
        # Check if the fully merged block can fit the meeting
        # The individual valid_intervals were checked for >= req_duration,
        # but if we had two adjacent 15m valid intervals making 30m total,
        # wait - the individual intervals in valid_intervals ALREADY pass the req_duration check individually!
        # Which means the block definitely fits.
        
        # We only generate ONE slot at the start of the contiguous block.
        slot_end = block_start + req_duration
        
        # Just an extra safeguard (though block_end >= slot_end is guaranteed)
        if slot_end <= block_end:
            slots.append(MeetingSlot(
                utc_start=block_start,
                utc_end=slot_end,
                duration_minutes=duration_minutes,
                satisfies_minimum=True
            ))

    # Step 5: Sort and return
    slots.sort(key=lambda s: s.utc_start)
    return slots
