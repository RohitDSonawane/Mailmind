"""
pipeline/handler.py — Main Pipeline Orchestrator.

Orchestrates all pipeline steps for a single inbound email. Routes by intent
and dispatches to the database and consensus checker.
"""

import logging
import sqlite3
import smtplib
from pydantic import ValidationError

from tools.gmail_reader import InboundEmail
from tools.gmail_sender import send_email
from database import dal
from pipeline import preprocessor, consensus
from agent import classifier, extractor, prompts
import config

logger = logging.getLogger(__name__)


def run_pipeline(
    conn: sqlite3.Connection,
    imap_conn,  # Type is imaplib.IMAP4_SSL but we don't strict import here to avoid circulars
    smtp_conn: smtplib.SMTP,
    inbound_email: InboundEmail,
    current_utc: str
) -> None:
    """
    Process a single inbound email through the scheduling pipeline.
    """
    msg_id = inbound_email.message_id
    if dal.is_processed(conn, msg_id):
        logger.info(f"Message {msg_id} already processed. Skipping.")
        return

    dal.mark_processed(conn, msg_id, current_utc)
    conn.commit()

    clean_body = preprocessor.preprocess_email_body(inbound_email.body_text)

    # Determine thread context
    thread_id = _find_thread_id(inbound_email)
    thread = dal.get_thread(conn, thread_id) if thread_id else None

    thread_status = thread["status"] if thread else "new"

    # Autoresponse check
    if inbound_email.auto_submitted and inbound_email.auto_submitted.lower() != "no":
        logger.info(f"Message {msg_id} is auto-submitted. Routing to NOISE.")
        return

    # Intent Classification
    intent_result = classifier.classify_intent(clean_body, thread_status, inbound_email.auto_submitted)
    intent_str = intent_result.intent
    logger.info(f"Message {msg_id} classified as {intent_str}.")

    # Route by Intent
    if intent_str == "noise":
        logger.info("Message classified as NOISE. Discarding.")
        return
    elif intent_str == "new_scheduling_request":
        _handle_new_request(conn, smtp_conn, inbound_email, current_utc)
    elif intent_str == "availability_reply":
        _handle_availability(conn, smtp_conn, inbound_email, clean_body, thread, thread_id, current_utc)
    elif intent_str == "confirmation":
        _handle_confirmation(conn, smtp_conn, inbound_email, thread, thread_id, current_utc)
    elif intent_str == "rejection":
        _handle_rejection(conn, smtp_conn, thread, thread_id, current_utc)


# ---------------------------------------------------------------------------
# Internal Handlers
# ---------------------------------------------------------------------------

def _find_thread_id(email: InboundEmail) -> str:
    """Find the thread ID from headers."""
    # In this system, the thread ID is the Message-ID of the original thread-starting email.
    if email.in_reply_to:
        return email.in_reply_to
    if email.references:
        # First reference is usually the root of the thread
        return email.references.split()[0]
    return ""


def _handle_new_request(conn: sqlite3.Connection, smtp_conn: smtplib.SMTP, email: InboundEmail, current_utc: str):
    thread_id = email.message_id
    if dal.get_thread(conn, thread_id):
        logger.info(f"Thread {thread_id} already exists for new request. Duplicate.")
        return

    subject = email.subject
    initiator = email.from_address
    participants_set = set(email.to_addresses + email.cc_addresses + [initiator])
    if config.GMAIL_ADDRESS in participants_set:
        participants_set.remove(config.GMAIL_ADDRESS)

    dal.insert_thread(conn, thread_id, subject, initiator, current_utc)
    
    for p in participants_set:
        is_init = (p == initiator)
        dal.insert_participant(conn, thread_id, p, is_init)
        
    conn.commit()

    # Send availability requests
    body = prompts.AVAILABILITY_REQUEST_CORE
    for p in participants_set:
        try:
            send_email(
                conn=smtp_conn,
                to_addresses=[p],
                subject=subject,
                body=body,
                in_reply_to=thread_id,
                references=thread_id
            )
        except Exception as e:
            logger.error(f"Failed to send AVAILABILITY_REQUEST to {p}: {e}")


def _handle_availability(conn: sqlite3.Connection, smtp_conn: smtplib.SMTP, email: InboundEmail, clean_body: str, thread: dict, thread_id: str, current_utc: str):
    if not thread:
        logger.warning("AVAILABILITY_REPLY with no existing thread context.")
        return

    if thread["status"] in ("proposal_sent", "completed"):
        logger.warning(f"AVAILABILITY_REPLY for thread {thread_id} in state {thread['status']}. Ignored.")
        return

    sender = email.from_address
    participants = dal.get_participants(conn, thread_id)
    participant_emails = {p["email_address"] for p in participants}

    # Roster expansion
    if sender not in participant_emails:
        if sender in email.cc_addresses:
            logger.info(f"Adding new CC participant {sender} to thread {thread_id}.")
            dal.insert_participant(conn, thread_id, sender, False)
            conn.commit()
            participant_emails.add(sender)
            # Send them an availability request so they know what to do if their reply didn't contain times
        else:
            logger.warning(f"Sender {sender} not in roster and not CC'd. Discarding availability reply.")
            return

    # Extract availability
    try:
        extraction_result = extractor.extract_availability(clean_body, current_utc, "UTC")
    except ValidationError as e:
        logger.error(f"Extraction failed for {sender}: {e}")
        return

    if extraction_result.windows:
        import json
        windows_list = [{"utc_start": w.utc_start.isoformat(), "utc_end": w.utc_end.isoformat()} for w in extraction_result.windows]
        windows_json = json.dumps(windows_list)
        
        dal.set_availability(conn, thread_id, sender, windows_json, extraction_result.inferred_timezone, current_utc)
        conn.commit()
        consensus.check_consensus(conn, smtp_conn, thread_id, current_utc)
    else:
        # Empty windows, ask for clarification
        try:
            send_email(
                conn=smtp_conn,
                to_addresses=[sender],
                subject=thread["subject"],
                body=prompts.CLARIFICATION_REQUEST_CORE,
                in_reply_to=thread_id,
                references=thread_id
            )
        except Exception as e:
            logger.error(f"Failed to send CLARIFICATION_REQUEST to {sender}: {e}")


def _handle_confirmation(conn: sqlite3.Connection, smtp_conn: smtplib.SMTP, email: InboundEmail, thread: dict, thread_id: str, current_utc: str):
    if not thread:
        logger.warning("CONFIRMATION with no existing thread context.")
        return

    if thread["status"] != "proposal_sent":
        logger.warning(f"CONFIRMATION for thread {thread_id} in state {thread['status']}. Ignored.")
        return

    sender = email.from_address
    participants = dal.get_participants(conn, thread_id)
    if sender not in [p["email_address"] for p in participants]:
        logger.warning(f"Sender {sender} not in roster. Discarding confirmation.")
        return

    dal.set_confirmed(conn, thread_id, sender, current_utc)
    conn.commit()
    consensus.check_consensus(conn, smtp_conn, thread_id, current_utc)


def _handle_rejection(conn: sqlite3.Connection, smtp_conn: smtplib.SMTP, thread: dict, thread_id: str, current_utc: str):
    if not thread:
        logger.warning("REJECTION with no existing thread context.")
        return

    if thread["status"] != "proposal_sent":
        logger.warning(f"REJECTION for thread {thread_id} in state {thread['status']}. Ignored.")
        return

    dal.reset_all_availability(conn, thread_id, current_utc)
    dal.clear_proposed_slot(conn, thread_id, current_utc)
    dal.update_thread_status(conn, thread_id, "awaiting_availability", current_utc)
    conn.commit()

    participants = dal.get_participants(conn, thread_id)
    recipients = [p["email_address"] for p in participants]
    try:
        send_email(
            conn=smtp_conn,
            to_addresses=recipients,
            subject=thread["subject"],
            body=prompts.SLOT_REJECTION_CORE,
            in_reply_to=thread_id,
            references=thread_id
        )
    except Exception as e:
        logger.error(f"Failed to send REJECTION_RESET email for thread {thread_id}: {e}")
