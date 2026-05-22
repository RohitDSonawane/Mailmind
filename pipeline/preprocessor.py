"""
pipeline/preprocessor.py — Email sanitisation pipeline.

Transforms a raw email body (HTML or plain text) into clean plain text
before it is passed to any LLM call.  This is the security boundary
between hostile external input and the internal pipeline.

Public API
----------
    preprocess_email_body(raw_body: str) -> str

The function applies five steps in order:
    1. HTML stripping
    2. Quoted-reply removal
    3. Signature removal
    4. Prompt injection filtering
    5. Final cleanup

Assumptions
-----------
- The caller always passes a single string (one email part).
- Multi-part selection (text/plain vs. text/html) is the responsibility
  of the IMAP reader (Phase 05).
- Line endings are normalised to LF (\n) at the top of the function.
"""

import re
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Sentinel returned when all content has been stripped
_NO_CONTENT = "[no parseable content]"

# -----------------------------------------------------------------------
# HTML detection
# -----------------------------------------------------------------------

_HTML_MARKERS = re.compile(
    r"<(?:html|body|p|div|br|table|span|td|tr|ul|ol|li|h[1-6]|a)\b",
    re.IGNORECASE,
)


def _is_html(text: str) -> bool:
    return bool(_HTML_MARKERS.search(text))


# -----------------------------------------------------------------------
# Step 1 — HTML stripping
# -----------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Parse HTML with BeautifulSoup and extract human-readable text."""
    soup = BeautifulSoup(text, "lxml")

    # Remove <style> and <script> blocks entirely
    for tag in soup(["style", "script", "head"]):
        tag.decompose()

    # Insert newlines before block-level elements so paragraphs separate
    for tag in soup.find_all(["p", "div", "br", "li", "tr", "h1", "h2",
                               "h3", "h4", "h5", "h6", "blockquote"]):
        tag.insert_before("\n")

    plain = soup.get_text(separator="")
    # Collapse excessive blank lines produced by block insertions
    plain = re.sub(r"\n{3,}", "\n\n", plain)
    return plain


# -----------------------------------------------------------------------
# Step 2 — Quoted-reply removal
# -----------------------------------------------------------------------

# Matches "On Mon, 6 Jan 2025 at 10:00 AM, John <j@x.com> wrote:"
_REPLY_HEADER_RE = re.compile(
    r"^on\s.{5,100}wrote\s*:?$",
    re.IGNORECASE,
)

# Forwarded message header
_FORWARDED_FROM_RE = re.compile(r"^from:\s+\S+@\S+", re.IGNORECASE)
_FORWARDED_HEADER_RE = re.compile(r"^-{3,}.*forwarded.*-{3,}$", re.IGNORECASE)

# Horizontal separators
_SEPARATOR_RE = re.compile(r"^(-{3,}|_{3,}|\*{3,})$")


def _remove_quoted_replies(text: str) -> str:
    """Remove everything from the first quote delimiter onward."""
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith(">")
            or _REPLY_HEADER_RE.match(stripped)
            or _SEPARATOR_RE.match(stripped)
            or _FORWARDED_FROM_RE.match(stripped)
            or _FORWARDED_HEADER_RE.match(stripped)
        ):
            break  # discard this line and everything after
        result.append(line)
    return "\n".join(result)


# -----------------------------------------------------------------------
# Step 3 — Signature removal
# -----------------------------------------------------------------------

_SIGNATURE_STARTERS = (
    "best,",
    "best regards,",
    "regards,",
    "thanks,",
    "thank you,",
    "cheers,",
    "sincerely,",
    "yours,",
    "warm regards,",
    "kind regards,",
    "sent from",
)

_SIG_DELIMITER_RE = re.compile(r"^(--|—)$")


def _remove_signature(text: str) -> str:
    """Remove email signature blocks."""
    lines = text.splitlines()
    result = []
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if _SIG_DELIMITER_RE.match(stripped):
            break
        if any(low.startswith(starter) for starter in _SIGNATURE_STARTERS):
            break
        result.append(line)
    return "\n".join(result)


# -----------------------------------------------------------------------
# Step 4 — Prompt injection filtering
# -----------------------------------------------------------------------

_INJECTION_PHRASES = re.compile(
    r"[^\n]*ignore\s+previous\s+instructions?[^\n]*"
    r"|[^\n]*disregard\s+your\s+instructions?[^\n]*"
    r"|[^\n]*you\s+are\s+now\s+[^\n]*"
    r"|[^\n]*your\s+new\s+instructions?\s+are[^\n]*"
    r"|[^\n]*\[system\][^\n]*"
    r"|<\s*system\s*>.*?<\s*/\s*system\s*>"
    r"|<\s*instructions?\s*>.*?<\s*/\s*instructions?\s*>"
    r"|<\s*prompt\s*>.*?<\s*/\s*prompt\s*>"
    r"|<\s*task\s*>.*?<\s*/\s*task\s*>",
    re.IGNORECASE | re.DOTALL,
)

# system: prefix at the start of a line
_SYSTEM_PREFIX_RE = re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE)


def _filter_prompt_injection(text: str) -> str:
    """Remove sentences/blocks containing known prompt injection patterns."""
    text = _INJECTION_PHRASES.sub("", text)
    # Remove lines that begin with "system:"
    lines = text.splitlines()
    lines = [l for l in lines if not _SYSTEM_PREFIX_RE.match(l.strip())]
    return "\n".join(lines)


# -----------------------------------------------------------------------
# Step 5 — Final cleanup
# -----------------------------------------------------------------------

def _final_cleanup(text: str) -> str:
    """Strip whitespace, collapse blank lines, return sentinel on empty."""
    text = text.strip()
    # Collapse three or more consecutive newlines to two
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return _NO_CONTENT
    return text


# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def preprocess_email_body(raw_body: str) -> str:
    """
    Sanitise a raw email body and return clean plain text.

    Parameters
    ----------
    raw_body : str
        The raw body of an inbound email.  May contain HTML, quoted reply
        history, an email signature, and/or prompt injection attempts.

    Returns
    -------
    str
        Clean plain-text content.  Returns "[no parseable content]" if
        all content was stripped by the pipeline.
    """
    if not raw_body or not raw_body.strip():
        return _NO_CONTENT

    # Normalise line endings
    text = raw_body.replace("\r\n", "\n").replace("\r", "\n")

    # Step 1 — HTML
    if _is_html(text):
        text = _strip_html(text)

    # Step 2 — Quoted replies
    text = _remove_quoted_replies(text)

    # Step 3 — Signatures
    text = _remove_signature(text)

    # Step 4 — Prompt injection
    text = _filter_prompt_injection(text)

    # Step 5 — Cleanup
    return _final_cleanup(text)
