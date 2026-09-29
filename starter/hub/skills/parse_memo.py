"""Extract structured intelligence from a rep voice-memo transcript."""

from __future__ import annotations

import json
from typing import Any

from hub.lib import logger
from hub.tools.llm_client import chat

_SYSTEM = (
    "You are a field intelligence analyst for a medical-imaging sales team. "
    "Parse messy voice memo transcripts from reps visiting hospitals and extract "
    "clean, structured intelligence. Be precise: only extract what is explicitly stated. "
    "Do NOT hallucinate contact names, competitors, or actions. "
    "Always respond with valid JSON matching the schema provided."
)

_SCHEMA = """{
  "accountId":  string | null,
  "competitor": string | null,
  "sentiment":  "positive" | "neutral" | "negative" | "mixed",
  "contacts":   [{ "name": string, "role": string, "sentiment": "positive"|"neutral"|"negative" }],
  "concerns":   string[],
  "nextAction": string | null,
  "urgency":    "low" | "normal" | "high" | "critical",
  "confidence": number (0–1)
}"""

_FALLBACK: dict[str, Any] = {
    "accountId": None, "competitor": None, "sentiment": "neutral",
    "contacts": [], "concerns": [], "nextAction": None, "urgency": "normal", "confidence": 0.0,
}

async def parse_memo(transcript: str, account_id: str | None = None) -> dict[str, Any]:
    """
    Extract structured field intelligence from a raw voice memo transcript.

    Args:
        transcript:  The raw spoken text from the rep.
        account_id:  Known accountId to anchor the extraction.

    Returns:
        ParsedMemo dict.
    """
    if not transcript:
        return {**_FALLBACK, "accountId": account_id}

    user_msg = (
        f"Account context: {account_id or 'unknown'}\n\n"
        f'Voice memo transcript:\n"""\n{transcript[:2_000]}\n"""\n\n'
        f"Extract the following as JSON:\n{_SCHEMA}"
    )

    try:
        raw = await chat(
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user_msg}],
            max_tokens=400,
            json_mode=True,
            context="parse-memo",
        )
        result: dict[str, Any] = json.loads(raw)
        if account_id:
            result["accountId"] = account_id
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warn("parse_memo failed", err=str(exc), account_id=account_id)
        return {**_FALLBACK, "accountId": account_id}
