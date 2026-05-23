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
            # Phase 09 - Call calendar adapter to create the event.
            if thread["calendar_event_id"]:
                logger.info(f"Thread {thread_id}: Calendar event already exists, skipping creation.")
            else:
                try:
                    slot_json = thread["proposed_slot"]
                    if not slot_json:
                        logger.error(f"Thread {thread_id}: Completed but no proposed_slot found.")
                        return

                    from agent.definitions import MeetingSlot
                    slot = MeetingSlot.model_validate_json(slot_json)

                    participants = dal.get_participants(conn, thread_id)
                    participant_emails = [p["email_address"] for p in participants]

                    clean_subject = gmail_sender.strip_subject_prefixes(thread["subject"])

                    from tools import calendar
                    event_id = calendar.create_event(clean_subject, slot.utc_start, slot.utc_end, participant_emails)

                    dal.set_calendar_event_id(conn, thread_id, event_id, current_utc)
                    conn.commit()
                except Exception as e:
                    logger.error(f"Thread {thread_id}: Failed to provision calendar event: {e}")
                    return

            try:
                slot_json = thread["proposed_slot"]
                from agent.definitions import MeetingSlot
                slot = MeetingSlot.model_validate_json(slot_json)
                import zoneinfo
                from datetime import timezone
                
                participants = dal.get_participants(conn, thread_id)
                initiator = next((p for p in participants if p["is_initiator"]), participants[0])
                tz_string = initiator.get("timezone") or config.DEFAULT_TIMEZONE
                try:
                    if tz_string == "UTC":
                        tz = timezone.utc
                    else:
                        tz = zoneinfo.ZoneInfo(tz_string)
                except zoneinfo.ZoneInfoNotFoundError:
                    logger.warning(f"Invalid timezone string {tz_string}, falling back to UTC")
                    tz = timezone.utc

                local_start = slot.utc_start.astimezone(tz)
                local_end = slot.utc_end.astimezone(tz)
                
                date_str = local_start.strftime("%Y-%m-%d")
                start_str = local_start.strftime("%H:%M")
                end_str = local_end.strftime("%H:%M")
                
                from agent.framing import compose_email_body
                framing_prompt = prompts.BOOKING_CONFIRMATION_FRAMING_PROMPT.format(
                    meeting_title=thread["subject"],
                    date=date_str,
                    time=f"{start_str} to {end_str}",
                    duration=f"{slot.duration_minutes}m"
                )
                
                body = compose_email_body(
                    email_type="booking_confirmation",
                    framing_prompt=framing_prompt,
                    core_template=prompts.BOOKING_CONFIRMATION_CORE_TEMPLATE,
                    template_vars={
                        "meeting_title": thread["subject"],
                        "date": date_str,
                        "start_time": start_str,
                        "end_time": end_str
                    }
                )

                participant_emails = [p["email_address"] for p in participants]

                gmail_sender.send_email(
                    conn=smtp_conn,
                    to_addresses=participant_emails,
                    subject=thread["subject"],
                    body=body,
                    in_reply_to=thread_id,
                    references=thread_id
                )
            except Exception as e:
                logger.error(f"Failed to send BOOKING_CONFIRMATION email for thread {thread_id}: {e}")

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
                from agent.framing import compose_email_body
                framing_prompt = prompts.EMPTY_INTERSECTION_FRAMING_PROMPT.format(
                    subject=thread["subject"],
                    participant_names=", ".join(recipients)
                )
                body = compose_email_body(
                    email_type="empty_intersection_notification",
                    framing_prompt=framing_prompt,
                    core_template=prompts.EMPTY_INTERSECTION_CORE,
                    template_vars={}
                )
                gmail_sender.send_email(
                    conn=smtp_conn,
                    to_addresses=recipients,
                    subject=thread["subject"],
                    body=body,
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
        import zoneinfo
        from datetime import timezone
        from agent.framing import compose_email_body
        
        participants = dal.get_participants(conn, thread_id)
        initiator = next((p for p in participants if p["is_initiator"]), participants[0])
        tz_string = initiator.get("timezone") or config.DEFAULT_TIMEZONE
        try:
            if tz_string == "UTC":
                tz = timezone.utc
            else:
                tz = zoneinfo.ZoneInfo(tz_string)
        except zoneinfo.ZoneInfoNotFoundError:
            logger.warning(f"Invalid timezone string {tz_string}, falling back to UTC")
            tz = timezone.utc

        local_start = proposed_slot.utc_start.astimezone(tz)
        local_end = proposed_slot.utc_end.astimezone(tz)

        date_str = local_start.strftime("%Y-%m-%d")
        start_str = local_start.strftime("%H:%M")
        end_str = local_end.strftime("%H:%M")
        
        framing_prompt = prompts.SLOT_PROPOSAL_FRAMING_PROMPT.format(
            subject=thread["subject"],
            date=date_str,
            start_time=start_str,
            end_time=end_str,
            timezone=str(tz)
        )
        
        body = compose_email_body(
            email_type="slot_proposal",
            framing_prompt=framing_prompt,
            core_template=prompts.SLOT_PROPOSAL_CORE_TEMPLATE,
            template_vars={
                "date": date_str,
                "start_time": start_str,
                "end_time": end_str,
                "timezone": str(tz)
            }
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
