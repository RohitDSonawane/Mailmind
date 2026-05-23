"""
agent/framing.py — Natural language framing generation.

Generates and heuristically validates framing sentences for outbound emails,
prepending or appending them to fixed factual cores.
"""

import logging
from groq import Groq
import config

logger = logging.getLogger(__name__)


def generate_framing(framing_prompt: str) -> str | None:
    """
    Generate natural language framing using Groq.

    Parameters
    ----------
    framing_prompt : str
        The full framing prompt string.

    Returns
    -------
    str | None
        The generated framing text stripped of whitespace, or None on failure.
    """
    try:
        client = Groq(api_key=config.GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": framing_prompt}],
            temperature=0.3,
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Failed to generate framing in groq: {e}")
        return None


def validate_framing(text: str) -> bool:
    """
    Heuristically validate generated framing text.

    Parameters
    ----------
    text : str
        The text to validate.

    Returns
    -------
    bool
        True if the text passes all checks, False otherwise.
    """
    if len(text) < 10 or len(text) > 200:
        return False

    lower_text = text.lower()
    
    prohibited_words = [
        "pydantic", "groq", "python", "sqlite", "llm", "model", 
        "ai", "bot", "automated", "system"
    ]
    for word in prohibited_words:
        if word in lower_text:
            return False

    prohibited_chars = ["json", "{", "}", "[", "]", "*", "#", "_", "`", "<", ">"]
    for char in prohibited_chars:
        if char in lower_text:
            return False

    if "\n\n" in text:
        return False

    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("-") or (len(line) > 1 and line[0].isdigit() and line[1] == "."):
            return False

    uncertainty_phrases = ["i think", "it seems", "perhaps", "maybe", "possibly"]
    for phrase in uncertainty_phrases:
        if phrase in lower_text:
            return False

    return True


def compose_email_body(email_type: str, framing_prompt: str, core_template: str, template_vars: dict) -> str:
    """
    Assemble the final email body by combining framing and the fixed core.

    Parameters
    ----------
    email_type : str
        The type of email (e.g. 'booking_confirmation').
    framing_prompt : str
        The filled framing prompt to send to the LLM.
    core_template : str
        The core template string.
    template_vars : dict
        Variables to substitute into the core template.

    Returns
    -------
    str
        The fully assembled email body.
    """
    try:
        core_filled = core_template.format(**template_vars)
    except KeyError as e:
        logger.error(f"Missing template variable {e} for {email_type} core template.")
        # Try to return the unformatted template or just fallback to empty string
        return core_template

    framing = generate_framing(framing_prompt)
    if not framing or not validate_framing(framing):
        return core_filled.strip()

    if email_type == "booking_confirmation":
        return f"{core_filled.strip()}\n\n{framing.strip()}"
    else:
        return f"{framing.strip()}\n\n{core_filled.strip()}"
