"""
database/schema.py — Authoritative SQLite schema for MailMind.

This file is the single reference for all table definitions, constraints,
and indexes. No business logic lives here — only CREATE TABLE statements.

Call initialize_schema(conn) once at application startup.
"""

CREATE_THREADS = """
CREATE TABLE IF NOT EXISTS threads (
    id                  TEXT PRIMARY KEY,
    subject             TEXT NOT NULL,
    initiator_address   TEXT NOT NULL,
    status              TEXT NOT NULL
                            CHECK(status IN (
                                'awaiting_availability',
                                'all_availability_received',
                                'proposal_sent',
                                'completed'
                            )),
    proposed_slot       TEXT,
    calendar_event_id   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
)
"""

CREATE_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS participants (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id                   TEXT    NOT NULL,
    email_address               TEXT    NOT NULL,
    is_initiator                INTEGER NOT NULL DEFAULT 0,
    has_submitted_availability  INTEGER NOT NULL DEFAULT 0,
    availability_windows        TEXT,
    timezone                    TEXT,
    has_confirmed               INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (thread_id) REFERENCES threads(id),
    UNIQUE (thread_id, email_address)
)
"""

CREATE_PROCESSED_EMAILS = """
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id      TEXT PRIMARY KEY,
    processed_at    TEXT NOT NULL
)
"""
