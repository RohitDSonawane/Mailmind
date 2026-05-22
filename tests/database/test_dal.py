"""
tests/database/test_dal.py — Unit tests for database/dal.py.

Every test uses a fresh in-memory SQLite connection (no file I/O).
The 'db' fixture creates the connection, initialises the schema, and
sets row_factory so results are accessible by column name.
"""

import sqlite3

import pytest

from database import dal


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def db() -> sqlite3.Connection:
    """Fresh in-memory SQLite with schema initialised."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    dal.initialize_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Helpers used across multiple tests
# ---------------------------------------------------------------------------

THREAD_ID = "msg-thread-001"
THREAD_ID_2 = "msg-thread-002"
TS = "2025-01-06T09:00:00Z"
TS2 = "2025-01-06T10:00:00Z"

PARTICIPANT_A = "alice@example.com"
PARTICIPANT_B = "bob@example.com"


def _insert_thread(db, thread_id=THREAD_ID, ts=TS):
    dal.insert_thread(db, thread_id, "Team Sync", PARTICIPANT_A, ts)
    db.commit()


def _insert_participant(db, thread_id=THREAD_ID, email=PARTICIPANT_A, initiator=True):
    dal.insert_participant(db, thread_id, email, initiator)
    db.commit()


# ---------------------------------------------------------------------------
# initialize_schema
# ---------------------------------------------------------------------------

class TestInitializeSchema:
    def test_idempotent_double_call(self, db):
        """Calling initialize_schema twice must not raise."""
        dal.initialize_schema(db)  # second call

    def test_tables_exist_after_init(self, db):
        """All three tables are present after initialisation."""
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "threads" in tables
        assert "participants" in tables
        assert "processed_emails" in tables

    def test_foreign_keys_enabled(self, db):
        """PRAGMA foreign_keys returns 1 after initialize_schema."""
        result = db.execute("PRAGMA foreign_keys").fetchone()[0]
        assert result == 1


# ---------------------------------------------------------------------------
# processed_emails
# ---------------------------------------------------------------------------

class TestProcessedEmails:
    def test_unknown_message_id_returns_false(self, db):
        assert dal.is_processed(db, "unknown-id") is False

    def test_mark_then_is_processed(self, db):
        dal.mark_processed(db, "msg-001", TS)
        assert dal.is_processed(db, "msg-001") is True

    def test_duplicate_message_id_raises(self, db):
        dal.mark_processed(db, "msg-001", TS)
        with pytest.raises(sqlite3.IntegrityError):
            dal.mark_processed(db, "msg-001", TS2)


# ---------------------------------------------------------------------------
# threads — insert and get
# ---------------------------------------------------------------------------

class TestInsertThread:
    def test_insert_and_get(self, db):
        _insert_thread(db)
        thread = dal.get_thread(db, THREAD_ID)
        assert thread is not None
        assert thread["id"] == THREAD_ID
        assert thread["subject"] == "Team Sync"
        assert thread["initiator_address"] == PARTICIPANT_A
        assert thread["status"] == "awaiting_availability"
        assert thread["proposed_slot"] is None
        assert thread["calendar_event_id"] is None
        assert thread["created_at"] == TS
        assert thread["updated_at"] == TS

    def test_get_unknown_thread_returns_none(self, db):
        assert dal.get_thread(db, "nonexistent") is None

    def test_duplicate_thread_id_raises(self, db):
        _insert_thread(db)
        with pytest.raises(sqlite3.IntegrityError):
            dal.insert_thread(db, THREAD_ID, "Another", PARTICIPANT_A, TS)
            db.commit()


# ---------------------------------------------------------------------------
# threads — status update
# ---------------------------------------------------------------------------

class TestUpdateThreadStatus:
    def test_valid_status_update(self, db):
        _insert_thread(db)
        dal.update_thread_status(db, THREAD_ID, "proposal_sent", TS2)
        db.commit()
        assert dal.get_thread(db, THREAD_ID)["status"] == "proposal_sent"

    def test_invalid_status_raises(self, db):
        _insert_thread(db)
        with pytest.raises(sqlite3.IntegrityError):
            dal.update_thread_status(db, THREAD_ID, "invalid_status", TS2)
            db.commit()

    def test_updated_at_is_refreshed(self, db):
        _insert_thread(db)
        dal.update_thread_status(db, THREAD_ID, "proposal_sent", TS2)
        db.commit()
        assert dal.get_thread(db, THREAD_ID)["updated_at"] == TS2


# ---------------------------------------------------------------------------
# threads — proposed_slot
# ---------------------------------------------------------------------------

class TestProposedSlot:
    def test_set_proposed_slot(self, db):
        _insert_thread(db)
        slot_json = '{"utc_start": "2025-01-07T10:00:00Z", "utc_end": "2025-01-07T11:00:00Z"}'
        dal.set_proposed_slot(db, THREAD_ID, slot_json, TS2)
        db.commit()
        assert dal.get_thread(db, THREAD_ID)["proposed_slot"] == slot_json

    def test_clear_proposed_slot(self, db):
        _insert_thread(db)
        slot_json = '{"utc_start": "2025-01-07T10:00:00Z"}'
        dal.set_proposed_slot(db, THREAD_ID, slot_json, TS)
        db.commit()
        dal.clear_proposed_slot(db, THREAD_ID, TS2)
        db.commit()
        assert dal.get_thread(db, THREAD_ID)["proposed_slot"] is None


# ---------------------------------------------------------------------------
# threads — calendar_event_id
# ---------------------------------------------------------------------------

class TestCalendarEventId:
    def test_set_calendar_event_id_and_completed(self, db):
        _insert_thread(db)
        dal.set_calendar_event_id(db, THREAD_ID, "cal-event-xyz", TS2)
        db.commit()
        thread = dal.get_thread(db, THREAD_ID)
        assert thread["calendar_event_id"] == "cal-event-xyz"
        assert thread["status"] == "completed"
        assert thread["updated_at"] == TS2


# ---------------------------------------------------------------------------
# participants — insert and get
# ---------------------------------------------------------------------------

class TestInsertParticipant:
    def test_insert_and_get_all(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        participants = dal.get_participants(db, THREAD_ID)
        assert len(participants) == 2

    def test_initiator_flag(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        by_email = {p["email_address"]: p for p in dal.get_participants(db, THREAD_ID)}
        assert by_email[PARTICIPANT_A]["is_initiator"] == 1
        assert by_email[PARTICIPANT_B]["is_initiator"] == 0

    def test_defaults_are_zero(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, False)
        db.commit()
        p = dal.get_participant(db, THREAD_ID, PARTICIPANT_A)
        assert p["has_submitted_availability"] == 0
        assert p["has_confirmed"] == 0
        assert p["availability_windows"] is None
        assert p["timezone"] is None

    def test_duplicate_participant_raises(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, False)
            db.commit()

    def test_get_participants_empty_thread(self, db):
        _insert_thread(db)
        assert dal.get_participants(db, THREAD_ID) == []

    def test_get_participant_unknown_returns_none(self, db):
        _insert_thread(db)
        assert dal.get_participant(db, THREAD_ID, "nobody@example.com") is None

    def test_foreign_key_enforced(self, db):
        """Inserting a participant for a non-existent thread_id raises."""
        with pytest.raises(sqlite3.IntegrityError):
            dal.insert_participant(db, "nonexistent-thread", PARTICIPANT_A, False)
            db.commit()


# ---------------------------------------------------------------------------
# participants — set_availability
# ---------------------------------------------------------------------------

class TestSetAvailability:
    def _setup(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        db.commit()

    def test_sets_has_submitted_and_windows(self, db):
        self._setup(db)
        windows_json = '[{"utc_start": "2025-01-07T09:00:00Z", "utc_end": "2025-01-07T12:00:00Z"}]'
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, windows_json, None, TS2)
        db.commit()
        p = dal.get_participant(db, THREAD_ID, PARTICIPANT_A)
        assert p["has_submitted_availability"] == 1
        assert p["availability_windows"] == windows_json

    def test_updates_timezone_when_provided(self, db):
        self._setup(db)
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", "Asia/Kolkata", TS2)
        db.commit()
        p = dal.get_participant(db, THREAD_ID, PARTICIPANT_A)
        assert p["timezone"] == "Asia/Kolkata"

    def test_does_not_overwrite_existing_timezone_when_none(self, db):
        """If timezone=None, an existing timezone must be preserved."""
        self._setup(db)
        # First call sets timezone
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", "America/New_York", TS)
        db.commit()
        # Second call passes timezone=None
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", None, TS2)
        db.commit()
        p = dal.get_participant(db, THREAD_ID, PARTICIPANT_A)
        assert p["timezone"] == "America/New_York"

    def test_refreshes_thread_updated_at(self, db):
        self._setup(db)
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", None, TS2)
        db.commit()
        thread = dal.get_thread(db, THREAD_ID)
        assert thread["updated_at"] == TS2


# ---------------------------------------------------------------------------
# participants — set_confirmed
# ---------------------------------------------------------------------------

class TestSetConfirmed:
    def test_sets_has_confirmed(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        db.commit()
        dal.set_confirmed(db, THREAD_ID, PARTICIPANT_A, TS2)
        db.commit()
        p = dal.get_participant(db, THREAD_ID, PARTICIPANT_A)
        assert p["has_confirmed"] == 1


# ---------------------------------------------------------------------------
# participants — reset_all_availability
# ---------------------------------------------------------------------------

class TestResetAllAvailability:
    def test_resets_all_flags_for_thread(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        # Give both participants availability
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, '[{"w": 1}]', "UTC", TS)
        dal.set_availability(db, THREAD_ID, PARTICIPANT_B, '[{"w": 2}]', "UTC", TS)
        dal.set_confirmed(db, THREAD_ID, PARTICIPANT_A, TS)
        db.commit()
        # Reset
        dal.reset_all_availability(db, THREAD_ID, TS2)
        db.commit()
        for p in dal.get_participants(db, THREAD_ID):
            assert p["has_submitted_availability"] == 0
            assert p["availability_windows"] is None
            assert p["has_confirmed"] == 0

    def test_does_not_affect_other_threads(self, db):
        """Participants in a different thread must not be touched."""
        # Thread 1 setup
        dal.insert_thread(db, THREAD_ID, "S1", PARTICIPANT_A, TS)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        db.commit()
        # Thread 2 setup
        dal.insert_thread(db, THREAD_ID_2, "S2", PARTICIPANT_B, TS)
        dal.insert_participant(db, THREAD_ID_2, PARTICIPANT_B, True)
        dal.set_availability(db, THREAD_ID_2, PARTICIPANT_B, '[]', "UTC", TS)
        db.commit()
        # Reset only thread 1
        dal.reset_all_availability(db, THREAD_ID, TS2)
        db.commit()
        p2 = dal.get_participant(db, THREAD_ID_2, PARTICIPANT_B)
        assert p2["has_submitted_availability"] == 1  # untouched


# ---------------------------------------------------------------------------
# Advancement condition queries
# ---------------------------------------------------------------------------

class TestAllAvailabilitySubmitted:
    def test_no_participants_returns_false(self, db):
        _insert_thread(db)
        assert dal.all_availability_submitted(db, THREAD_ID) is False

    def test_one_missing_returns_false(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", None, TS)
        db.commit()
        assert dal.all_availability_submitted(db, THREAD_ID) is False

    def test_all_submitted_returns_true(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        dal.set_availability(db, THREAD_ID, PARTICIPANT_A, "[]", None, TS)
        dal.set_availability(db, THREAD_ID, PARTICIPANT_B, "[]", None, TS)
        db.commit()
        assert dal.all_availability_submitted(db, THREAD_ID) is True


class TestAllConfirmed:
    def test_no_participants_returns_false(self, db):
        _insert_thread(db)
        assert dal.all_confirmed(db, THREAD_ID) is False

    def test_one_unconfirmed_returns_false(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        dal.set_confirmed(db, THREAD_ID, PARTICIPANT_A, TS)
        db.commit()
        assert dal.all_confirmed(db, THREAD_ID) is False

    def test_all_confirmed_returns_true(self, db):
        _insert_thread(db)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_A, True)
        dal.insert_participant(db, THREAD_ID, PARTICIPANT_B, False)
        db.commit()
        dal.set_confirmed(db, THREAD_ID, PARTICIPANT_A, TS)
        dal.set_confirmed(db, THREAD_ID, PARTICIPANT_B, TS)
        db.commit()
        assert dal.all_confirmed(db, THREAD_ID) is True
