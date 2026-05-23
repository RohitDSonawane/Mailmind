"""
tools/gmail_reader.py — IMAP adapter for connecting to Gmail.

Encapsulates IMAP protocol logic: fetching unseen messages, parsing MIME
payloads into clean datastructures, and marking messages as seen.
"""

import imaplib
import email
import logging
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class InboundEmail:
    """Parsed representation of a raw inbound email."""
    uid: str
    message_id: str
    subject: str
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    auto_submitted: Optional[str]
    body_text: str
    in_reply_to: Optional[str]
    references: Optional[str]
    sender_timezone_offset: Optional[str] = None


# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------

def connect(gmail_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    """
    Connect and authenticate to Gmail via IMAP over SSL.

    Parameters
    ----------
    gmail_address : str
        The bot's email address.
    app_password : str
        The app password for IMAP access.

    Returns
    -------
    imaplib.IMAP4_SSL
        The authenticated and selected IMAP connection.

    Raises
    ------
    imaplib.IMAP4.error
        If connection, authentication, or mailbox selection fails.
    """
    try:
        conn = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        conn.login(gmail_address, app_password)
        conn.select("INBOX")
        return conn
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP connection failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Internal Helpers: Header Parsing
# ---------------------------------------------------------------------------

def _parse_single_address(header_value: Optional[str]) -> str:
    """Extract a lowercase email address from a From header."""
    if not header_value:
        return ""
    _, addr = parseaddr(header_value)
    return addr.strip().lower()


def _parse_addresses(header_value: Optional[str]) -> list[str]:
    """Parse comma-separated addresses from To/CC headers."""
    if not header_value:
        return []
    addresses = []
    for _, addr in getaddresses([header_value]):
        clean_addr = addr.strip().lower()
        if clean_addr:
            addresses.append(clean_addr)
    return addresses


def _parse_message_id(header_value: Optional[str]) -> str:
    """Strip angle brackets from Message-ID."""
    if not header_value or not header_value.strip():
        raise ValueError("Missing or empty Message-ID header.")
    return header_value.strip().strip("<>")


# ---------------------------------------------------------------------------
# Internal Helpers: Body Extraction
# ---------------------------------------------------------------------------

def _extract_body(msg: Message) -> str:
    """
    Extract the best available plain-text body from a MIME message.

    Priority:
    1. text/plain
    2. text/html
    3. empty string
    """
    plain_part = None
    html_part = None

    # walk() iterates over all parts, including nested multipart boundaries
    for part in msg.walk():
        if part.is_multipart():
            continue

        content_type = part.get_content_type()
        if content_type == "text/plain" and plain_part is None:
            plain_part = part
        elif content_type == "text/html" and html_part is None:
            html_part = part

    target_part = plain_part or html_part
    if target_part is None:
        return ""

    payload = target_part.get_payload(decode=True)
    if payload is None:
        return ""

    charset = target_part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        # If the charset is unknown/invalid, fallback to latin-1
        return payload.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# Polling and Execution
# ---------------------------------------------------------------------------

def fetch_unseen(conn: imaplib.IMAP4_SSL) -> list[InboundEmail]:
    """
    Fetch and parse all unseen emails from the INBOX.

    Parameters
    ----------
    conn : imaplib.IMAP4_SSL
        The authenticated IMAP connection.

    Returns
    -------
    list[InboundEmail]
        A list of parsed emails.
    """
    try:
        typ, data = conn.uid("SEARCH", None, "UNSEEN")
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP search failed: {e}")
        raise

    if typ != "OK" or not data[0]:
        return []

    uids = data[0].split()
    emails = []

    for uid in uids:
        uid_str = uid.decode("ascii")
        try:
            # Fetch the full raw payload for this UID using PEEK to prevent auto-marking as Seen
            fetch_typ, fetch_data = conn.uid("FETCH", uid_str, "(BODY.PEEK[])")
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP fetch failed for UID {uid_str}: {e}")
            raise

        if fetch_typ != "OK" or not fetch_data:
            continue

        # fetch_data looks like: [(b'1 (UID 100 RFC822 {size}', b'raw...'), b')']
        # Extract the raw email bytes
        raw_email_bytes = None
        for item in fetch_data:
            if isinstance(item, tuple):
                raw_email_bytes = item[1]
                break

        if not raw_email_bytes:
            continue

        msg = email.message_from_bytes(raw_email_bytes)

        # Parse headers
        try:
            msg_id = _parse_message_id(msg.get("Message-ID"))
        except ValueError as e:
            logger.warning(f"Skipping UID {uid_str}: {e}")
            raise  # Spec requires raising on missing Message-ID

        subject = str(msg.get("Subject", ""))
        from_address = _parse_single_address(msg.get("From"))
        to_addresses = _parse_addresses(msg.get("To"))
        cc_addresses = _parse_addresses(msg.get("CC"))
        auto_submitted = msg.get("Auto-Submitted")
        
        in_reply_to_raw = msg.get("In-Reply-To")
        in_reply_to = in_reply_to_raw.strip().strip("<>") if in_reply_to_raw else None
        
        references_raw = msg.get("References")
        references = references_raw.strip() if references_raw else None

        body_text = _extract_body(msg)

        # Parse timezone offset from Date header
        sender_timezone_offset = None
        date_str = msg.get("Date")
        if date_str:
            try:
                dt = parsedate_to_datetime(date_str)
                if dt.tzinfo:
                    sender_timezone_offset = dt.strftime("%z")  # e.g., '+0530'
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to parse Date header for UID {uid_str}: {e}")

        emails.append(InboundEmail(
            uid=uid_str,
            message_id=msg_id,
            subject=subject,
            from_address=from_address,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            auto_submitted=auto_submitted,
            body_text=body_text,
            in_reply_to=in_reply_to,
            references=references,
            sender_timezone_offset=sender_timezone_offset
        ))

    return emails


def mark_seen(conn: imaplib.IMAP4_SSL, uid: str) -> None:
    """
    Mark an email as seen by applying the \\Seen flag.

    Parameters
    ----------
    conn : imaplib.IMAP4_SSL
        The authenticated IMAP connection.
    uid : str
        The persistent IMAP UID of the message.
    """
    try:
        typ, data = conn.uid("STORE", uid, "+FLAGS", "\\Seen")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"Failed to mark UID {uid} as seen: {data}")
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP mark_seen failed for UID {uid}: {e}")
        raise
