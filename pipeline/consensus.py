"""
pipeline/consensus.py — Consensus Checker.

Evaluates the thread's state to determine if phase transitions should occur.
Triggers intersection, slot proposal, or calendar provisioning when ready.
"""

import logging
import json
import sqlite3
import smtplib

from database import dal
from pipeline import intersection
from agent.definitions import AvailabilityWindow
from agent import prompts
from tools import gmail_sender
import config

logger = logging.getLogger(__name__)


def check_consensus(conn: sqlite3.Connection, smtp_conn: smtplib.SMTP, thread_id: str, current_utc: str) -> None:
    """
    Check the current thread state and advance the scheduling phase if conditions are met.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection.
    smtp_conn : smtplib.SMTP
        Authenticated SMTP connection.
    thread_id : str
        The ID of the thread to check.
    current_utc : str
        The current UTC timestamp (ISO 8601).
    """
    thread = dal.get_thread(conn, thread_id)
    if not thread:
        logger.error(f"check_consensus: Thread {thread_id} not found.")
        return

    status = thread["status"]

    if status == "completed":
        return

    if status == "proposal_sent":
        if dal.all_confirmed(conn, thread_id):
            logger.info(f"Thread {thread_id}: All participants confirmed. Triggering calendar provisioning.")
            # TODO: Phase 09 - Call calendar adapter to create the event.
            return
        else:
            return  # Still waiting for confirmations

    if status in ("awaiting_availability", "all_availability_received"):
        if not dal.all_availability_submitted(conn, thread_id):
            return  # Still waiting

        logger.info(f"Thread {thread_id}: All availability received. Running intersection.")
        dal.update_thread_status(conn, thread_id, "all_availability_received", current_utc)
        conn.commit()

        participants = dal.get_participants(conn, thread_id)
        windows_by_participant = {}

        for p in participants:
            email = p["email_address"]
            raw_windows = p["availability_windows"]
            windows = []
            if raw_windows:
                try:
                    parsed = json.loads(raw_windows)
                    # Convert to AvailabilityWindow objects
                    from datetime import datetime
                    for w in parsed:
                        windows.append(AvailabilityWindow(
                            utc_start=datetime.fromisoformat(w["utc_start"]),
                            utc_end=datetime.fromisoformat(w["utc_end"])
                        ))
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f"Failed to parse windows for {email} in thread {thread_id}: {e}")
                    # Treat as empty
                    pass
            windows_by_participant[email] = windows

        valid_slots = intersection.find_valid_slots(windows_by_participant, config.MEETING_DURATION_MINUTES)

        if not valid_slots:
            logger.info(f"Thread {thread_id}: No overlapping slots found. Resetting availability.")
            # Single transaction: reset thread
            dal.reset_all_availability(conn, thread_id, current_utc)
            dal.update_thread_status(conn, thread_id, "awaiting_availability", current_utc)
            conn.commit()

            # Send group email
            recipients = [p["email_address"] for p in participants if not p["is_initiator"]]
            if not recipients:
                recipients = [p["email_address"] for p in participants]

            try:
                gmail_sender.send_email(
                    conn=smtp_conn,
                    to_addresses=recipients,
                    subject=thread["subject"],
                    body=prompts.EMPTY_INTERSECTION_CORE,
                    in_reply_to=thread_id,
                    references=thread_id
                )
            except Exception as e:
                logger.error(f"Failed to send EMPTY_INTERSECTION email for thread {thread_id}: {e}")
            return

        # Proposal Flow
        logger.info(f"Thread {thread_id}: Overlap found. Sending proposal.")
        proposed_slot = valid_slots[0]
        slot_dict = {
            "utc_start": proposed_slot.utc_start.isoformat(),
            "utc_end": proposed_slot.utc_end.isoformat(),
            "duration_minutes": proposed_slot.duration_minutes
        }
        slot_json = json.dumps(slot_dict)

        dal.set_proposed_slot(conn, thread_id, slot_json, current_utc)
        dal.update_thread_status(conn, thread_id, "proposal_sent", current_utc)
        conn.commit()

        # Format proposal email body
        date_str = proposed_slot.utc_start.strftime("%Y-%m-%d")
        start_str = proposed_slot.utc_start.strftime("%H:%M")
        end_str = proposed_slot.utc_end.strftime("%H:%M")
        body = prompts.SLOT_PROPOSAL_CORE_TEMPLATE.format(
            date=date_str,
            start_time=start_str,
            end_time=end_str,
            timezone="UTC"
        )

        recipients = [p["email_address"] for p in participants]
        try:
            gmail_sender.send_email(
                conn=smtp_conn,
                to_addresses=recipients,
                subject=thread["subject"],
                body=body,
                in_reply_to=thread_id,
                references=thread_id
            )
        except Exception as e:
            logger.error(f"Failed to send SLOT_PROPOSAL email for thread {thread_id}: {e}")
        return
