"""Account Intelligence — Market Signals + CRM → expansion signals, revenue estimates, pre-call briefs."""

from __future__ import annotations

import json
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "account_intelligence"

_EXPANSION_SYSTEM = (
    "You are a medical-imaging sales analyst. "
    "Given an expansion announcement, estimate: type (greenfield/wing/merger/capex_refresh), "
    "imaging categories affected, and addressable revenue in EUR/USD. "
    "Return JSON: {\"expansionType\": str, \"categories\": [str], \"addressableRevenue\": number, "
    "\"confidence\": float, \"urgency\": \"low\"|\"normal\"|\"high\"|\"critical\"}"
)

async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]
    account_id = payload.get("accountId", "")

    match t:
        case "account_synced":
                        state.upsert_account(account_id, {
                "name":        payload.get("name", ""),
                "healthScore": payload.get("healthScore", 80),
            })

        case "expansion_announcement":
            # Genuine judgement required — LLM call justified
            result = await _classify_expansion(payload, sim_time)
            if result:
                state.add_signal(account_id, {
                    "source":   "market",
                    "type":     "expansion_detected",
                    "summary":  f"Expansion: {result.get('expansionType')} — €{result.get('addressableRevenue', 0):,}",
                    "simTime":  sim_time,
                    "severity": "high",
                })
                rev = float(result.get("addressableRevenue", 0))
                emit(
                    sim_time=sim_time,
                    agent=_AGENT,
                    action="expansion_announcement",
                    account_id=account_id,
                    value=rev,
                    currency="EUR",
                    reach=1,
                    reversible=True,
                    external=False,
                    extra={
                        "expansionType": result.get("expansionType"),
                        "categories":    result.get("categories", []),
                        "confidence":    result.get("confidence", 0.7),
                    },
                )

        case "budget_cycle_open":
            # Rule-based: flag if budget > €1M, no LLM
            amount = payload.get("approvedAmount", 0)
            if amount >= 1_000_000:
                state.add_signal(account_id, {
                    "source":   "market",
                    "type":     "budget_cycle_open",
                    "amount":   amount,
                    "expires":  payload.get("expiresAt"),
                    "summary":  f"Budget open: €{amount:,}. Expires {payload.get('expiresAt','')[:10]}",
                    "simTime":  sim_time,
                    "severity": "high",
                })

        case "rfq_published":
            state.add_signal(account_id, {
                "source":   "market", "type": "rfq_published",
                "tenderRef": payload.get("tenderRef"),
                "value":    payload.get("estimatedValue", 0),
                "summary":  f"RFQ: {payload.get('title','')}",
                "simTime":  sim_time, "severity": "critical",
            })

        case _:
            logger.debug("AccountIntelligence: skipped", type=t)

async def _classify_expansion(payload: dict[str, Any], sim_time: str) -> dict[str, Any] | None:
    try:
        description = payload.get("description") or payload.get("type", "")
        raw = await chat(
            messages=[
                {"role": "system", "content": _EXPANSION_SYSTEM},
                {"role": "user",   "content": f"Announcement: {description}\nBudget: {payload.get('capexBudget', 'unknown')}\nImaging budget: {payload.get('imagingBudget', 'unknown')}"},
            ],
            max_tokens=300,
            json_mode=True,
            context="account-intelligence-expansion",
        )
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warn("Expansion classification failed", err=str(exc))
        return {"expansionType": "unknown", "categories": [], "addressableRevenue": 0, "confidence": 0.5, "urgency": "normal"}
