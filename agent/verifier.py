"""
verifier.py — Self-verification loop for LLM-generated narratives.

After the reasoner produces a draft, this module passes the narrative back
to the LLM with the raw numbers and asks it to fact-check its own claims.
This is a lightweight agentic pattern that catches hallucinated statistics
without the overhead of a full agent framework.

If USE_LLM is False, the verifier simply returns the draft unchanged.
"""
from __future__ import annotations

import re
from typing import Any

import config

_VERIFY_PROMPT = """You are a fact-checker. A narrative was written about a project.
Your job is to verify that every number mentioned in the narrative matches the
source data provided below. If a number is wrong or fabricated, correct it.
If everything is accurate, return the narrative unchanged.

DO NOT add new information. DO NOT change the tone or structure.
ONLY fix factual errors. Return the corrected narrative and nothing else.

SOURCE DATA:
{data_summary}

NARRATIVE TO CHECK:
{narrative}
"""


def verify(
    narrative: str,
    scores: dict[str, Any],
    mc: dict[str, Any],
) -> tuple[str, bool]:
    """
    Run one self-verification pass on the narrative.

    Returns
    -------
    (verified_narrative, was_modified)
    """
    if not config.USE_LLM:
        return narrative, False

    try:
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning, module="google")
        import google.generativeai as genai
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(config.GEMINI_MODEL)

        data_summary = (
            f"RAG: {scores['rag']}\n"
            f"Project Score: {scores['project_score']}\n"
            f"Forward Risk: {scores['forward_risk']}\n"
            f"Historical Slip: {scores['historical_slip']}\n"
            f"Completed tasks: {scores['task_summary']['by_status'].get('Completed', 0)}\n"
            f"In Progress tasks: {scores['task_summary']['by_status'].get('In Progress', 0)}\n"
            f"Not Started tasks: {scores['task_summary']['by_status'].get('Not Started', 0)}\n"
            f"On Hold tasks: {scores['task_summary']['by_status'].get('On Hold', 0)}\n"
            f"Red tasks: {scores['task_summary']['by_rag'].get('Red', 0)}\n"
            f"Yellow tasks: {scores['task_summary']['by_rag'].get('Yellow', 0)}\n"
            f"Green tasks: {scores['task_summary']['by_rag'].get('Green', 0)}\n"
            f"P(on-time): {mc.get('p_on_time', 'N/A')}\n"
            f"Deadline: {mc.get('deadline', 'N/A')}\n"
            f"Median finish date: {mc.get('median_finish_date', 'N/A')}\n"
        )

        prompt = _VERIFY_PROMPT.format(
            data_summary=data_summary,
            narrative=narrative,
        )

        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1, "max_output_tokens": 500},
        )
        verified = response.text.strip()
        was_modified = verified.strip() != narrative.strip()
        return verified, was_modified

    except Exception as exc:
        # Verification failure is non-fatal — return original narrative
        return narrative + f"\n\n[Verification skipped: {exc}]", False
