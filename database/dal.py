"""
database/dal.py — Data Access Layer for MailMind.

ALL SQL in the application lives here. No other module may construct or
execute raw SQL. Every function accepts a sqlite3.Connection as its first
parameter so tests can inject an in-memory connection.

Naming convention:
  - Readers return None / [] / bool — they never raise on empty results.
  - Writers commit their own transaction unless the docstring says otherwise.
  - Functions that reset multiple fields in a single atomic step are named
    clearly (e.g. reset_all_availability) and documented.
"""

import json
import logging
import sqlite3

from database.schema import (
    CREATE_PARTICIPANTS,
    CREATE_PROCESSED_EMAILS,
    CREATE_THREADS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def initialize_schema(conn: sqlite3.Connection) -> None:
    """
    Create all tables if they do not exist, and enable foreign-key enforcement.
    Safe to call multiple times (idempotent via IF NOT EXISTS).
    """
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(CREATE_THREADS)
    conn.execute(CREATE_PARTICIPANTS)
    conn.execute(CREATE_PROCESSED_EMAILS)
    conn.commit()


# ---------------------------------------------------------------------------
# processed_emails
# ---------------------------------------------------------------------------

def is_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    """Return True if message_id is already in the processed_emails table."""
    row = conn.execute(
        "SELECT 1 FROM processed_emails WHERE message_id = ?",
        (message_id,),
    ).fetchone()
    return row is not None


def mark_processed(
    conn: sqlite3.Connection,
    message_id: str,
    processed_at: str,
) -> None:
    """Insert a record into processed_emails for a fully handled message."""
    conn.execute(
        "INSERT INTO processed_emails (message_id, processed_at) VALUES (?, ?)",
        (message_id, processed_at),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# threads
# ---------------------------------------------------------------------------

def insert_thread(
    conn: sqlite3.Connection,
    id: str,
    subject: str,
    initiator_address: str,
    created_at: str,
) -> None:
    """
    Insert a new thread with status 'awaiting_availability'.
    Both created_at and updated_at are set to the provided timestamp.
    """
    conn.execute(
        """
        INSERT INTO threads
            (id, subject, initiator_address, status, created_at, updated_at)
        VALUES (?, ?, ?, 'awaiting_availability', ?, ?)
        """,
        (id, subject, initiator_address, created_at, created_at),
    )
    # Caller is responsible for committing (usually part of a larger transaction).


def get_thread(conn: sqlite3.Connection, thread_id: str) -> dict | None:
    """Return the thread row as a dict, or None if not found."""
    row = conn.execute(
        "SELECT * FROM threads WHERE id = ?",
        (thread_id,),
    ).fetchone()
    return dict(row) if row else None


def update_thread_status(
    conn: sqlite3.Connection,
    thread_id: str,
    status: str,
    updated_at: str,
) -> None:
    """Update threads.status and refresh updated_at."""
    conn.execute(
        "UPDATE threads SET status = ?, updated_at = ? WHERE id = ?",
        (status, updated_at, thread_id),
    )


def set_proposed_slot(
    conn: sqlite3.Connection,
    thread_id: str,
    proposed_slot_json: str,
    updated_at: str,
) -> None:
    """Store a JSON-serialised MeetingSlot in threads.proposed_slot."""
    conn.execute(
        "UPDATE threads SET proposed_slot = ?, updated_at = ? WHERE id = ?",
        (proposed_slot_json, updated_at, thread_id),
    )


def clear_proposed_slot(
    conn: sqlite3.Connection,
    thread_id: str,
    updated_at: str,
) -> None:
    """Set threads.proposed_slot back to NULL."""
    conn.execute(
        "UPDATE threads SET proposed_slot = NULL, updated_at = ? WHERE id = ?",
        (updated_at, thread_id),
    )


def set_calendar_event_id(
    conn: sqlite3.Connection,
    thread_id: str,
    event_id: str,
    updated_at: str,
) -> None:
    """
    Store the Google Calendar event ID and advance status to 'completed'.
    Called only after a successful events.insert API call.
    """
    conn.execute(
        """
        UPDATE threads
        SET calendar_event_id = ?,
            status = 'completed',
            updated_at = ?
        WHERE id = ?
        """,
        (event_id, updated_at, thread_id),
    )


# ---------------------------------------------------------------------------
# participants
# ---------------------------------------------------------------------------

def insert_participant(
    conn: sqlite3.Connection,
    thread_id: str,
    email_address: str,
    is_initiator: bool,
) -> None:
    """
    Insert a participant row with all boolean flags at their default (0).
    Raises sqlite3.IntegrityError on duplicate (thread_id, email_address).
    """
    conn.execute(
        """
        INSERT INTO participants
            (thread_id, email_address, is_initiator)
        VALUES (?, ?, ?)
        """,
        (thread_id, email_address, int(is_initiator)),
    )


def get_participants(conn: sqlite3.Connection, thread_id: str) -> list[dict]:
    """Return all participant rows for a thread as a list of dicts."""
    rows = conn.execute(
        "SELECT * FROM participants WHERE thread_id = ?",
        (thread_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_participant(
    conn: sqlite3.Connection,
    thread_id: str,
    email_address: str,
) -> dict | None:
    """Return one participant row or None if not found."""
    row = conn.execute(
        "SELECT * FROM participants WHERE thread_id = ? AND email_address = ?",
        (thread_id, email_address),
    ).fetchone()
    return dict(row) if row else None


def set_availability(
    conn: sqlite3.Connection,
    thread_id: str,
    email_address: str,
    windows_json: str,
    timezone: str | None,
    updated_at: str,
) -> None:
    """
    Store serialised availability windows and mark the participant as having
    submitted. If timezone is not None, updates the participant's timezone field;
    if None, leaves any existing timezone value intact.

    Also refreshes threads.updated_at in the same call.
    Caller must commit after this call (usually part of a larger transaction).
    """
    if timezone is not None:
        conn.execute(
            """
            UPDATE participants
            SET availability_windows        = ?,
                has_submitted_availability  = 1,
                timezone                    = ?
            WHERE thread_id = ? AND email_address = ?
            """,
            (windows_json, timezone, thread_id, email_address),
        )
    else:
        conn.execute(
            """
            UPDATE participants
            SET availability_windows        = ?,
                has_submitted_availability  = 1
            WHERE thread_id = ? AND email_address = ?
            """,
            (windows_json, thread_id, email_address),
        )
    conn.execute(
        "UPDATE threads SET updated_at = ? WHERE id = ?",
        (updated_at, thread_id),
    )


def set_confirmed(
    conn: sqlite3.Connection,
    thread_id: str,
    email_address: str,
    updated_at: str,
) -> None:
    """Set has_confirmed = 1 for a participant and refresh threads.updated_at."""
    conn.execute(
        """
        UPDATE participants
        SET has_confirmed = 1
        WHERE thread_id = ? AND email_address = ?
        """,
        (thread_id, email_address),
    )
    conn.execute(
        "UPDATE threads SET updated_at = ? WHERE id = ?",
        (updated_at, thread_id),
    )


def reset_all_availability(
    conn: sqlite3.Connection,
    thread_id: str,
    updated_at: str,
) -> None:
    """
    Clear all availability and confirmation data for every participant in
    the thread.  Called on:
      - empty intersection (no valid slot found)
      - rejection of a proposed slot

    Caller must commit (usually part of a larger atomic reset transaction).
    """
    conn.execute(
        """
        UPDATE participants
        SET has_submitted_availability  = 0,
            availability_windows        = NULL,
            has_confirmed               = 0
        WHERE thread_id = ?
        """,
        (thread_id,),
    )
    conn.execute(
        "UPDATE threads SET updated_at = ? WHERE id = ?",
        (updated_at, thread_id),
    )


# ---------------------------------------------------------------------------
# Advancement condition queries
# ---------------------------------------------------------------------------

def all_availability_submitted(conn: sqlite3.Connection, thread_id: str) -> bool:
    """
    Return True only if ALL participants in the thread have
    has_submitted_availability = 1. Returns False for threads with no
    participants (a thread with no participants has satisfied nothing).
    """
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                        AS total,
            SUM(has_submitted_availability)                 AS submitted
        FROM participants
        WHERE thread_id = ?
        """,
        (thread_id,),
    ).fetchone()
    total, submitted = row["total"], row["submitted"]
    return total > 0 and total == submitted


def all_confirmed(conn: sqlite3.Connection, thread_id: str) -> bool:
    """
    Return True only if ALL participants in the thread have has_confirmed = 1.
    Returns False for threads with no participants.
    """
    row = conn.execute(
        """
        SELECT
            COUNT(*)            AS total,
            SUM(has_confirmed)  AS confirmed
        FROM participants
        WHERE thread_id = ?
        """,
        (thread_id,),
    ).fetchone()
    total, confirmed = row["total"], row["confirmed"]
    return total > 0 and total == confirmed
