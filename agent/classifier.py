"""
agent/classifier.py — Intent classification agent.
"""

from typing import Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.groq import GroqModel

from agent.definitions import ClassificationResult
from agent.prompts import CLASSIFIER_SYSTEM_PROMPT
import config


# ---------------------------------------------------------------------------
# Agent Definition
# ---------------------------------------------------------------------------

classifier_agent = Agent(
    model=GroqModel("llama-3.3-70b-versatile"),
    output_type=ClassificationResult,
    system_prompt=CLASSIFIER_SYSTEM_PROMPT,
    retries=2,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(
    clean_body: str,
    thread_status: str,
    auto_submitted_header: Optional[str] = None
) -> ClassificationResult:
    """
    Classify the intent of an inbound email.

    Parameters
    ----------
    clean_body : str
        The preprocessed plain text body of the email.
    thread_status : str
        The current status of the thread in the database, or 'new' if none exists.
    auto_submitted_header : str | None
        The value of the 'Auto-Submitted' header, if present.

    Returns
    -------
    ClassificationResult
        The structured classification result.

    Raises
    ------
    ValidationError (from pydantic) if the model output violates the schema.
    Exception (from groq) on API failure.
    """
    # Deterministic short-circuit for out-of-office replies
    if auto_submitted_header and auto_submitted_header.strip().lower() != "no":
        return ClassificationResult(
            intent="noise",
            confidence=1.0,
            reasoning=f"Auto-Submitted header present: {auto_submitted_header}",
        )

    # Dynamic system prompt context
    prompt_context = {"thread_status": thread_status}

    # Execute the agent
    result = classifier_agent.run_sync(
        user_prompt=clean_body,
        deps=prompt_context,
    )
    return result.data


# ---------------------------------------------------------------------------
# Dynamic Prompt Formatting
# ---------------------------------------------------------------------------

@classifier_agent.system_prompt
def _format_system_prompt(ctx: RunContext[dict]) -> str:
    """Inject thread status into the system prompt."""
    return CLASSIFIER_SYSTEM_PROMPT.format(thread_status=ctx.deps["thread_status"])
