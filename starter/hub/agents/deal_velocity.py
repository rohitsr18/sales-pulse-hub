"""Deal Velocity — CRM opportunity age → stuck-deal detection (>30 days), root cause, unstick actions. Detection is a number comparison; one LLM call per stalled deal."""

from __future__ import annotations

import json
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "deal_velocity"
_STALL_THRESHOLD = 30  # days — business decision, not a technical one; NHS can run longer

_UNSTICK_SYSTEM = (
    "You are a deal-coaching expert for medical imaging sales. "
    "Given a stuck deal, identify the most likely root cause and the single best unstick action. "
    "Return JSON: {\"rootCause\": str, \"unstickAction\": str, \"confidence\": float, "
    "\"timingHours\": number}"
)

async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "opportunity_created":
                        state.upsert_opportunity(payload["accountId"], {
                "oppId":       payload["oppId"],
                "title":       payload.get("title", ""),
                "value":       payload.get("value", 0),
                "stage":       payload.get("stage", ""),
                "probability": payload.get("probability", 0.5),
                "products":    payload.get("products", []),
                "repId":       payload.get("repId"),
                "createdAt":   sim_time,
                "daysInStage": 0,
            })

        case "opportunity_stalled":
            # Update repId in case it changed
            state.upsert_opportunity(payload["accountId"], {
                "oppId":  payload["oppId"],
                "repId":  payload.get("repId"),
                "daysInStage": payload.get("daysInStage", 0),
            })
            days = payload.get("daysInStage", 0)
            if days >= _STALL_THRESHOLD:
                await _handle_stuck_deal(payload, sim_time, days)

        case "opportunity_risk_flagged":
            account_id = payload.get("accountId", "")
            state.upsert_opportunity(account_id, {
                "oppId":      payload["oppId"],
                "riskType":   payload.get("riskType"),
                "riskDetail": payload.get("riskDetail"),
                "repId":      payload.get("repId"),
                "value":      payload.get("value", 0),
            })
            state.add_risk_flag(account_id, payload.get("riskType", "unknown_risk"))
            state.recompute_health(account_id)
            # A risk-flagged opp is effectively stalled — emit deal stall
            await _handle_stuck_deal(payload, sim_time, days=0)
            # A flagged delivery/stall risk is functionally a stuck deal — emit as stall
            await _handle_stuck_deal(payload, sim_time, 30)

        case "opportunity_stage_changed":
            state.upsert_opportunity(payload.get("accountId", ""), {
                "oppId":        payload.get("oppId"),
                "stage":        payload.get("newStage"),
                "daysInStage":  0,
                "lastMovedAt":  sim_time,
            })

        case "contact_sentiment_changed":
            account_id = payload.get("accountId", "")
            state.upsert_contact(account_id, {
                "contactId": payload.get("contactId", ""),
                "name":      payload.get("contactName", ""),
                "role":      payload.get("role", ""),
                "sentiment": payload.get("toSentiment", "neutral"),
            })
            if payload.get("toSentiment") in ("cold", "negative"):
                state.add_risk_flag(account_id, "contact_cold")
                state.recompute_health(account_id)

        case _:
            pass

async def _handle_stuck_deal(payload: dict[str, Any], sim_time: str, days: int) -> None:
    account_id = payload.get("accountId", "")
    opp_id     = payload.get("oppId", "")
    value      = float(payload.get("value", 0))

    state.add_risk_flag(account_id, "quote_stalled")
    state.add_signal(account_id, {
        "source":  "crm",
        "type":    "deal_stall",
        "oppId":   opp_id,
        "days":    days,
        "value":   value,
        "summary": f"Deal stalled {days}d in stage '{payload.get('stage')}' — €{value:,}",
        "simTime": sim_time,
        "severity": "high",
    })
    state.recompute_health(account_id)

    # ONE LLM call — root cause + unstick recommendation
    result = await _get_unstick_action(account_id, payload, days)

    # Emit stall detection (LOW blast — internal signal)
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="deal_stall",
        account_id=account_id,
        opportunity_id=opp_id,
        value=value,
        reach=1,
        reversible=True,
        external=False,
        extra={
            "daysInStage": days,
            "stage":       payload.get("stage"),
            "rootCause":   result.get("rootCause"),
            "unstickAction": result.get("unstickAction"),
            "confidence":  result.get("confidence", 0.6),
            "timingHours": result.get("timingHours", 24),
        },
    )

    logger.warn(
        "Deal stall detected",
        accountId=account_id,
        oppId=opp_id,
        days=days,
        rootCause=result.get("rootCause"),
    )

async def _get_unstick_action(
    account_id: str,
    payload: dict[str, Any],
    days: int,
) -> dict[str, Any]:
    acc = state.get_account(account_id)
    signals = state.get_signals(account_id, limit=5)
    signal_summary = "; ".join(s.get("summary", "") for s in signals)

    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _UNSTICK_SYSTEM},
                {"role": "user", "content":
                    f"Account: {acc.get('name', account_id) if acc else account_id}\n"
                    f"Opportunity: {payload.get('title')} (€{payload.get('value',0):,})\n"
                    f"Stage: {payload.get('stage')} — stalled {days} days\n"
                    f"Recent signals: {signal_summary or 'none'}\n"
                    "Identify root cause and unstick action."},
            ],
            max_tokens=250,
            json_mode=True,
            context="unstick",
        )
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warn("Unstick action generation failed", err=str(exc))
        return {"rootCause": "unknown", "unstickAction": "manual_review", "confidence": 0.4, "timingHours": 24}
