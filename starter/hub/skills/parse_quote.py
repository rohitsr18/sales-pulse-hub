"""Classify and extract structure from an inbound quote email."""

from __future__ import annotations

import json
from typing import Any

from hub.lib import logger
from hub.tools.llm_client import chat

_SYSTEM = (
    "You are a sales operations analyst for a medical-imaging company. "
    "Given an inbound quote request email, classify the deal tier and extract product details. "
    "Capital equipment (MRI, CT, Interventional X-ray) costs >$200K per unit. "
    "Service contracts and consumables are under $200K/unit. Respond only with valid JSON."
)

_SCHEMA = """{
  "accountId":       string | null,
  "tier":            "consumable" | "capital",
  "products":        [{ "name": string, "qty": number, "productId": string|null, "notes": string|null }],
  "urgency":         "low" | "normal" | "high" | "critical",
  "budgetConfirmed": boolean,
  "deadline":        string | null,
  "serviceYears":    number | null,
  "estimatedValue":  number | null,
  "tenderRef":       string | null,
  "confidence":      number (0–1)
}"""

_FALLBACK: dict[str, Any] = {
    "accountId": None, "tier": "capital", "products": [],
    "urgency": "normal", "budgetConfirmed": False, "deadline": None,
    "serviceYears": None, "estimatedValue": None, "tenderRef": None, "confidence": 0.0,
}

async def parse_quote(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Classify an inbound quote request and extract structured fields.

    Args:
        payload: Raw quote event payload.

    Returns:
        ParsedQuote dict.
    """
    account_id   = payload.get("accountId")
    from_contact = payload.get("fromContact", "unknown")
    subject      = str(payload.get("subject", ""))[:200]
    body         = str(payload.get("body", ""))[:3_000]
    attachments  = "\n".join(payload.get("attachmentsText") or [])[:500] or "none"

    user_msg = (
        f"Account: {account_id or 'unknown'}\n"
        f"From: {from_contact}\n"
        f"Subject: {subject}\n"
        f'Body:\n"""\n{body}\n"""\n'
        f"Attachments text: {attachments}\n\n"
        f"Extract as JSON:\n{_SCHEMA}"
    )

    try:
        raw = await chat(
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user_msg}],
            max_tokens=500,
            json_mode=True,
            context="parse-quote",
        )
        result: dict[str, Any] = json.loads(raw)
        if account_id:
            result["accountId"] = account_id
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warn("parse_quote failed", err=str(exc), account_id=account_id)
        return {**_FALLBACK, "accountId": account_id}
