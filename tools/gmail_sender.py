"""
tools/gmail_sender.py — SMTP adapter for sending outbound emails via Gmail.

Encapsulates SMTP protocol logic: establishing STARTTLS connections,
constructing plain-text MIME messages with correct threading headers,
and dispatching them.
"""

import smtplib
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from email.header import Header

import config

logger = logging.getLogger(__name__)

# Precompiled regex for stripping subject prefixes (e.g. Re:, Fwd:)
_SUBJECT_PREFIX_RE = re.compile(r"^(?:re|fwd|fw):\s*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def strip_subject_prefixes(subject: str) -> str:
    """
    Remove all leading 'Re:', 'Fwd:', 'Fw:' prefixes from a subject string.

    Parameters
    ----------
    subject : str
        The original subject string.

    Returns
    -------
    str
        The cleaned subject, trimmed of whitespace.
    """
    cleaned = subject.strip()
    while True:
        new_cleaned = _SUBJECT_PREFIX_RE.sub("", cleaned).strip()
        if new_cleaned == cleaned:
            break
        cleaned = new_cleaned
    return cleaned


# ---------------------------------------------------------------------------
# Connection Management
# ---------------------------------------------------------------------------

def connect(gmail_address: str, app_password: str) -> smtplib.SMTP:
    """
    Connect and authenticate to Gmail via SMTP with STARTTLS.

    Parameters
    ----------
    gmail_address : str
        The bot's email address.
    app_password : str
        The app password for SMTP access.

    Returns
    -------
    smtplib.SMTP
        The authenticated SMTP connection.

    Raises
    ------
    smtplib.SMTPException
        If connection, TLS negotiation, or authentication fails.
    """
    try:
        conn = smtplib.SMTP("smtp.gmail.com", 587)
        conn.ehlo()
        conn.starttls()
        conn.ehlo()
        conn.login(gmail_address, app_password)
        return conn
    except smtplib.SMTPException as e:
        logger.error(f"SMTP connection failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_email(
    conn: smtplib.SMTP,
    to_addresses: list[str],
    subject: str,
    body: str,
    in_reply_to: str,
    references: str
) -> str:
    """
    Construct and send a plain-text email with threading headers.

    Parameters
    ----------
    conn : smtplib.SMTP
        The authenticated SMTP connection.
    to_addresses : list[str]
        A list of recipient email addresses.
    subject : str
        The email subject.
    body : str
        The plain-text email body.
    in_reply_to : str
        The Message-ID of the email this is replying to (without angle brackets).
    references : str
        The accumulated chain of Message-IDs in the thread (space-separated, without angle brackets).

    Returns
    -------
    str
        The freshly generated Message-ID (without angle brackets) of the sent email.

    Raises
    ------
    smtplib.SMTPException
        If sending the message fails.
    """
    msg = MIMEMultipart("alternative")
    
    # Generate new Message-ID with angle brackets
    raw_msg_id = make_msgid(domain="gmail.com")
    clean_msg_id = raw_msg_id.strip("<>")
    
    msg["Message-ID"] = raw_msg_id
    msg["In-Reply-To"] = f"<{in_reply_to}>" if in_reply_to else ""
    
    # Ensure references are space-separated and wrapped in angle brackets
    if references:
        ref_list = [f"<{r.strip()}>" for r in references.split()]
        msg["References"] = " ".join(ref_list)
    else:
        msg["References"] = ""

    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = ", ".join(to_addresses)
    msg["Subject"] = Header(subject, "utf-8")

    # Attach the plain-text body
    part = MIMEText(body, "plain", "utf-8")
    msg.attach(part)

    try:
        conn.sendmail(config.GMAIL_ADDRESS, to_addresses, msg.as_string())
        return clean_msg_id
    except smtplib.SMTPException as e:
        logger.error(f"SMTP send_email failed for {to_addresses}: {e}")
        raise
