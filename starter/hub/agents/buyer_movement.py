"""Buyer Movement — Market Signals people moves → threat/opportunity classification and outreach. One LLM call per executive-change event."""

from __future__ import annotations

import json
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "buyer_movement"

_CLASSIFY_SYSTEM = (
    "You are a sales intelligence analyst. "
    "Given an executive change at a hospital, classify as threat or opportunity. "
    "Return JSON: {\"classification\": \"threat\"|\"opportunity\"|\"neutral\", "
    "\"confidence\": float, \"reasoning\": str, "
    "\"recommendedOutreach\": str | null, \"urgencyHours\": number}"
)

async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "executive_change":
            await _handle_exec_change(payload, sim_time)

        case "competitor_activity":
            account_id = payload.get("accountId", "")
            if payload.get("activityType") in ("proposal_submitted", "demo_conducted"):
                state.add_risk_flag(account_id, "competitor_active")
                state.add_signal(account_id, {
                    "source":     "market",
                    "type":       "competitor_threat",
                    "competitor": payload.get("competitor"),
                    "summary":    f"Competitor {payload.get('competitor')} active: {payload.get('activityType')}",
                    "simTime":    sim_time,
                    "severity":   "high",
                })
                emit(
                    sim_time=sim_time,
                    agent=_AGENT,
                    action="competitor_rfp",
                    account_id=account_id,
                    value=_estimate_pipeline_value(account_id),
                    reach=1,
                    reversible=True,
                    external=False,
                    extra={
                        "competitor":    payload.get("competitor"),
                        "activityType":  payload.get("activityType"),
                    },
                )

        case _:
            pass

async def _handle_exec_change(payload: dict[str, Any], sim_time: str) -> None:
    account_id = payload.get("accountId", "")
    role       = payload.get("role", "unknown")
    new_name   = payload.get("newName", "unknown")
    mandate    = payload.get("mandate", "")

    state.add_risk_flag(account_id, "exec_change")
    state.upsert_contact(account_id, {
        "contactId": payload.get("contactId", f"exec-{role.lower()}"),
        "name":      new_name,
        "role":      role,
        "sentiment": "unknown",
        "mandate":   mandate,
    })
    state.add_signal(account_id, {
        "source":  "market",
        "type":    "executive_change",
        "role":    role,
        "newName": new_name,
        "mandate": mandate,
        "summary": f"New {role}: {new_name}. Mandate: {mandate or 'unknown'}",
        "simTime": sim_time,
        "severity": "high",
    })
    state.recompute_health(account_id)

    # ONE LLM call — classify threat/opportunity
    result = await _classify_move(account_id, payload)

    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="buyer_movement",
        account_id=account_id,
        value=_estimate_pipeline_value(account_id),
        reach=1,
        reversible=True,
        external=False,
        extra={
            "role":               role,
            "newBuyer":           new_name,
            "classification":     result.get("classification", "neutral"),
            "confidence":         result.get("confidence", 0.5),
            "reasoning":          result.get("reasoning", ""),
            "recommendedOutreach":result.get("recommendedOutreach"),
            "urgencyHours":       result.get("urgencyHours", 48),
        },
    )

    logger.info(
        "Buyer move classified",
        accountId=account_id,
        role=role,
        classification=result.get("classification"),
        confidence=result.get("confidence"),
    )

async def _classify_move(account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    acc = state.get_account(account_id)
    opps = list((acc.get("opportunities") or {}).values()) if acc else []
    pipeline = sum(o.get("value", 0) for o in opps)

    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content":
                    f"Account: {acc.get('name', account_id) if acc else account_id}\n"
                    f"Role changed: {payload.get('role')}\n"
                    f"New person: {payload.get('newName')}\n"
                    f"Mandate: {payload.get('mandate', 'unknown')}\n"
                    f"Open pipeline: €{pipeline:,}\n"
                    "Classify this buyer move."},
            ],
            max_tokens=300,
            json_mode=True,
            context="buyer-move",
        )
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warn("Buyer move classification failed", err=str(exc))
        return {"classification": "neutral", "confidence": 0.5, "reasoning": "Classification unavailable", "recommendedOutreach": None, "urgencyHours": 48}

def _estimate_pipeline_value(account_id: str) -> float:
    acc = state.get_account(account_id)
    if not acc:
        return 0.0
    opps = acc.get("opportunities") or {}
    opps_list = opps.values() if isinstance(opps, dict) else opps
    return float(sum(o.get("value", 0) for o in opps_list))
