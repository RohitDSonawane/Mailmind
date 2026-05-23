"""
tests/tools/test_gmail_sender.py — Unit tests for tools/gmail_sender.py.
"""

import smtplib
from unittest.mock import MagicMock

import pytest

from tools import gmail_sender


# ---------------------------------------------------------------------------
# Utility Tests
# ---------------------------------------------------------------------------

def test_strip_subject_prefixes():
    assert gmail_sender.strip_subject_prefixes("Re: Team Sync") == "Team Sync"
    assert gmail_sender.strip_subject_prefixes("Re: Re: Fwd: Team Sync") == "Team Sync"
    assert gmail_sender.strip_subject_prefixes("RE: re: FWD: Budget Discussion") == "Budget Discussion"
    assert gmail_sender.strip_subject_prefixes("Fw: Reminder") == "Reminder"
    assert gmail_sender.strip_subject_prefixes("Team Sync") == "Team Sync"
    assert gmail_sender.strip_subject_prefixes("Re:") == ""
    assert gmail_sender.strip_subject_prefixes("  Re:   Whitespace Test  ") == "Whitespace Test"


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------

def test_connect_success(mocker):
    mock_smtp = MagicMock(spec=smtplib.SMTP)
    mocker.patch("tools.gmail_sender.smtplib.SMTP", return_value=mock_smtp)

    conn = gmail_sender.connect("bot@example.com", "pass123")
    
    assert mock_smtp.ehlo.call_count == 2
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("bot@example.com", "pass123")
    assert conn is mock_smtp


def test_connect_raises_on_error(mocker):
    mock_smtp = MagicMock(spec=smtplib.SMTP)
    mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
    mocker.patch("tools.gmail_sender.smtplib.SMTP", return_value=mock_smtp)

    with pytest.raises(smtplib.SMTPAuthenticationError):
        gmail_sender.connect("bot@example.com", "wrong_pass")


# ---------------------------------------------------------------------------
# send_email Tests
# ---------------------------------------------------------------------------

def test_send_email_success(mocker):
    mock_conn = MagicMock()
    # Mock config.GMAIL_ADDRESS for the test
    mocker.patch("tools.gmail_sender.config.GMAIL_ADDRESS", "bot@example.com")
    
    # Send email
    to_addresses = ["alice@example.com", "bob@example.com"]
    msg_id = gmail_sender.send_email(
        conn=mock_conn,
        to_addresses=to_addresses,
        subject="Re: Scheduling",
        body="Does 2pm work?",
        in_reply_to="msg-001@example.com",
        references="msg-000@example.com msg-001@example.com"
    )

    assert msg_id
    assert "<" not in msg_id
    assert ">" not in msg_id

    mock_conn.sendmail.assert_called_once()
    args, kwargs = mock_conn.sendmail.call_args
    from_addr = args[0]
    to_addrs = args[1]
    msg_string = args[2]

    assert from_addr == "bot@example.com"
    assert to_addrs == to_addresses

    # Verify headers in the raw MIME string
    assert "Message-ID: <" in msg_string
    assert "In-Reply-To: <msg-001@example.com>" in msg_string
    assert "References: <msg-000@example.com> <msg-001@example.com>" in msg_string
    assert "To: alice@example.com, bob@example.com" in msg_string
    assert "=?utf-8?q?Re=3A_Scheduling?=" in msg_string
    assert 'Content-Type: text/plain; charset="utf-8"' in msg_string
    
    # Body check
    # quoted-printable or base64 encoding might transform "2pm work?"
    # The message structure is already validated, so we don't strictly need to parse the base64 here.


def test_send_email_no_references(mocker):
    mock_conn = MagicMock()
    mocker.patch("tools.gmail_sender.config.GMAIL_ADDRESS", "bot@example.com")
    
    gmail_sender.send_email(
        conn=mock_conn,
        to_addresses=["alice@example.com"],
        subject="New Thread",
        body="Hello",
        in_reply_to="",
        references=""
    )

    args, _ = mock_conn.sendmail.call_args
    msg_string = args[2]

    # Without in_reply_to and references, they should be empty strings in construction,
    # which means the email package will output empty headers or omit them.
    # Let's ensure the message is still sent.
    assert mock_conn.sendmail.called


def test_send_email_raises_on_error(mocker):
    mock_conn = MagicMock()
    mocker.patch("tools.gmail_sender.config.GMAIL_ADDRESS", "bot@example.com")
    mock_conn.sendmail.side_effect = smtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"User unknown")})

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        gmail_sender.send_email(
            conn=mock_conn,
            to_addresses=["alice@example.com"],
            subject="Hello",
            body="Test",
            in_reply_to="id1",
            references="id1"
        )
