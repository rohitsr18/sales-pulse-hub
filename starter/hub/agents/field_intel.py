"""Field Intel — voice memo transcripts → structured competitor/contact/sentiment signals."""

from __future__ import annotations

from typing import Any

from hub.lib import logger
from hub.skills.parse_memo import parse_memo
from hub.store.world_state import state

async def handle(event: dict[str, Any]) -> None:
    if event["type"] != "voice_memo_received":
        return

    payload    = event["payload"]
    account_id = payload.get("accountId")
    transcript = payload.get("transcript", "")
    rep_id     = payload.get("repId", "?")

    logger.info("Processing voice memo", accountId=account_id, repId=rep_id, durationSec=payload.get("durationSec"))

    intel = await parse_memo(transcript, account_id)

    # Update contacts extracted by LLM
    for contact in intel.get("contacts") or []:
        if contact.get("name"):
            state.upsert_contact(account_id or "", {
                "contactId": f"voice-{contact['name'].lower().replace(' ', '-')}",
                "name":      contact["name"],
                "role":      contact.get("role", ""),
                "sentiment": contact.get("sentiment", "neutral"),
            })

    # Record competitor signal
    competitor = intel.get("competitor")
    if competitor:
        state.add_risk_flag(account_id or "", "competitor_active")
        state.add_signal(account_id or "", {
            "source":     "voice",
            "type":       "competitor_mention",
            "competitor": competitor,
            "repId":      rep_id,
            "sentiment":  intel.get("sentiment", "neutral"),
            "concerns":   intel.get("concerns", []),
            "nextAction": intel.get("nextAction"),
            "summary":    f"Competitor {competitor} mentioned by {rep_id}. Sentiment: {intel.get('sentiment')}.",
            "simTime":    payload.get("capturedAt") or event["simTime"],
            "severity":   "high",
        })
        state.recompute_health(account_id or "")
        logger.warn("Competitor detected in memo", accountId=account_id, competitor=competitor, repId=rep_id)
    else:
        state.add_signal(account_id or "", {
            "source":    "voice",
            "type":      "field_memo",
            "repId":     rep_id,
            "sentiment": intel.get("sentiment", "neutral"),
            "concerns":  intel.get("concerns", []),
            "summary":   f"Memo from {rep_id}: {intel.get('sentiment')} sentiment. Action: {intel.get('nextAction') or 'none'}",
            "simTime":   payload.get("capturedAt") or event["simTime"],
            "severity":  "medium" if intel.get("sentiment") == "negative" else "low",
        })
