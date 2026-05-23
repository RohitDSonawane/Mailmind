"""
tests/tools/test_gmail_reader.py — Unit tests for tools/gmail_reader.py.
"""

import imaplib
import email
from email.message import Message
from unittest.mock import MagicMock

import pytest

from tools import gmail_reader
from tools.gmail_reader import InboundEmail


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------

def test_connect_success(mocker):
    mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
    mocker.patch("tools.gmail_reader.imaplib.IMAP4_SSL", return_value=mock_imap)

    conn = gmail_reader.connect("bot@example.com", "pass123")
    
    mock_imap.login.assert_called_once_with("bot@example.com", "pass123")
    mock_imap.select.assert_called_once_with("INBOX")
    assert conn is mock_imap


def test_connect_raises_on_error(mocker):
    mock_imap = MagicMock(spec=imaplib.IMAP4_SSL)
    mock_imap.login.side_effect = imaplib.IMAP4.error("Login failed")
    mocker.patch("tools.gmail_reader.imaplib.IMAP4_SSL", return_value=mock_imap)

    with pytest.raises(imaplib.IMAP4.error, match="Login failed"):
        gmail_reader.connect("bot@example.com", "wrong_pass")


# ---------------------------------------------------------------------------
# Address Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_single_address():
    assert gmail_reader._parse_single_address('"John Smith" <john@example.com>') == "john@example.com"
    assert gmail_reader._parse_single_address("<alice@example.com>") == "alice@example.com"
    assert gmail_reader._parse_single_address("BOB@example.com") == "bob@example.com"
    assert gmail_reader._parse_single_address(None) == ""


def test_parse_addresses():
    assert gmail_reader._parse_addresses('"John" <john@example.com>, alice@example.com') == ["john@example.com", "alice@example.com"]
    assert gmail_reader._parse_addresses("") == []
    assert gmail_reader._parse_addresses(None) == []


# ---------------------------------------------------------------------------
# Body Extraction Tests
# ---------------------------------------------------------------------------

def test_extract_body_plain_text():
    msg = Message()
    msg.set_payload("Hello world", charset="utf-8")
    msg.set_type("text/plain")
    assert gmail_reader._extract_body(msg) == "Hello world"


def test_extract_body_html_fallback():
    msg = Message()
    msg.set_payload("<p>Hello HTML</p>", charset="utf-8")
    msg.set_type("text/html")
    assert gmail_reader._extract_body(msg) == "<p>Hello HTML</p>"


def test_extract_body_empty_no_match():
    msg = Message()
    msg.set_type("image/png")
    msg.set_payload(b"fakebytes")
    assert gmail_reader._extract_body(msg) == ""


def test_extract_body_multipart_priority():
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<p>HTML</p>", "html"))
    msg.attach(MIMEText("Plain", "plain"))

    assert gmail_reader._extract_body(msg) == "Plain"


# ---------------------------------------------------------------------------
# mark_seen Tests
# ---------------------------------------------------------------------------

def test_mark_seen_success(mocker):
    mock_conn = MagicMock()
    mock_conn.uid.return_value = ("OK", [b"Success"])
    gmail_reader.mark_seen(mock_conn, "123")
    mock_conn.uid.assert_called_once_with("STORE", "123", "+FLAGS", "\\Seen")


def test_mark_seen_raises_on_error(mocker):
    mock_conn = MagicMock()
    mock_conn.uid.side_effect = imaplib.IMAP4.error("STORE error")
    with pytest.raises(imaplib.IMAP4.error):
        gmail_reader.mark_seen(mock_conn, "123")


# ---------------------------------------------------------------------------
# fetch_unseen Tests
# ---------------------------------------------------------------------------

def test_fetch_unseen_empty(mocker):
    mock_conn = MagicMock()
    mock_conn.uid.return_value = ("OK", [b""])
    emails = gmail_reader.fetch_unseen(mock_conn)
    assert emails == []


def test_fetch_unseen_success(mocker):
    from email.mime.text import MIMEText
    msg = MIMEText("Hello test", "plain", "utf-8")
    msg["Message-ID"] = "<msg-123@example.com>"
    msg["Subject"] = "Test Subject"
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "bot@example.com"
    msg["Auto-Submitted"] = "auto-replied"

    raw_bytes = msg.as_bytes()

    mock_conn = MagicMock()
    # Mock SEARCH
    mock_conn.uid.side_effect = [
        ("OK", [b"100"]),  # First call: SEARCH -> b"100"
        ("OK", [(b'100 (UID 100 RFC822 {size}', raw_bytes), b')']) # Second call: FETCH
    ]

    emails = gmail_reader.fetch_unseen(mock_conn)
    
    assert len(emails) == 1
    em = emails[0]
    assert em.uid == "100"
    assert em.message_id == "msg-123@example.com"
    assert em.subject == "Test Subject"
    assert em.from_address == "alice@example.com"
    assert em.to_addresses == ["bot@example.com"]
    assert em.auto_submitted == "auto-replied"
    assert em.body_text == "Hello test"


def test_fetch_unseen_missing_message_id_raises(mocker):
    from email.mime.text import MIMEText
    msg = MIMEText("Hello test", "plain", "utf-8")
    # No Message-ID
    raw_bytes = msg.as_bytes()

    mock_conn = MagicMock()
    mock_conn.uid.side_effect = [
        ("OK", [b"100"]),
        ("OK", [(b'100 (UID 100 RFC822 {size}', raw_bytes), b')'])
    ]

    with pytest.raises(ValueError, match="Missing or empty Message-ID"):
        gmail_reader.fetch_unseen(mock_conn)
