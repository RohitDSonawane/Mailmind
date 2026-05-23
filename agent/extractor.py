"""
agent/extractor.py — Availability extraction agent.
"""

from typing import Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel

from agent.definitions import ExtractorResult
from agent.prompts import EXTRACTOR_SYSTEM_PROMPT
import config


# ---------------------------------------------------------------------------
# Agent Definition
# ---------------------------------------------------------------------------

extractor_agent = Agent(
    model=GroqModel("llama-3.1-8b-instant"),
    output_type=ExtractorResult,
    system_prompt=EXTRACTOR_SYSTEM_PROMPT,
    retries=2,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_availability(
    clean_body: str,
    current_utc: str,
    participant_timezone: Optional[str] = None
) -> ExtractorResult:
    """
    Extract concrete UTC time windows from an availability reply.

    Parameters
    ----------
    clean_body : str
        The preprocessed plain text body of the email.
    current_utc : str
        The current UTC time in ISO 8601 format, used as the reference point for
        relative dates ("next Tuesday").
    participant_timezone : str | None
        The known timezone of the participant, if any (e.g. "Europe/London").

    Returns
    -------
    ExtractorResult
        A list of AvailabilityWindow objects (strictly UTC) and any inferred timezone.
        If the email is ambiguous or provides no times, the windows list is empty.

    Raises
    ------
    ValidationError (from pydantic) if the model output violates the schema (e.g. end <= start).
    Exception (from groq) on API failure.
    """
    # Dynamic system prompt context
    prompt_context = {
        "current_utc": current_utc,
        "participant_timezone": participant_timezone or "None",
    }

    # Execute the agent
    result = extractor_agent.run_sync(
        user_prompt=clean_body,
        deps=prompt_context,
    )
    return result.data


# ---------------------------------------------------------------------------
# Dynamic Prompt Formatting
# ---------------------------------------------------------------------------

@extractor_agent.system_prompt
def _format_system_prompt(ctx: RunContext[dict]) -> str:
    """Inject current UTC and participant timezone into the system prompt."""
    return EXTRACTOR_SYSTEM_PROMPT.format(
        current_utc=ctx.deps["current_utc"],
        participant_timezone=ctx.deps["participant_timezone"],
    )
