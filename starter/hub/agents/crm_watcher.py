"""Lightweight CRM state-sync: updates WorldState from CRM events, sets risk flags. No LLM calls."""

from __future__ import annotations

from typing import Any

from hub.lib import logger
from hub.store.world_state import state

_STALL_DAYS = 21  # flag an opportunity as stalled after this many inactive days

async def handle(event: dict[str, Any]) -> None:
    t       = event["type"]
    payload = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "account_synced":
            patch: dict[str, Any] = {"healthScore": payload.get("healthScore", 80)}
            if payload.get("name"):  # never overwrite a snapshot-loaded name with empty string
                patch["name"] = payload["name"]
            state.upsert_account(payload["accountId"], patch)
            logger.debug("Account synced", accountId=payload["accountId"])

        case "opportunity_created":
            state.upsert_opportunity(payload["accountId"], {
                "oppId":       payload["oppId"],
                "title":       payload.get("title", ""),
                "value":       payload.get("value", 0),
                "stage":       payload.get("stage", ""),
                "probability": payload.get("probability", 0.5),
                "products":    payload.get("products", []),
                "createdAt":   sim_time,
            })
            state.add_signal(payload["accountId"], {
                "source":  "crm",
                "type":    "opportunity_created",
                "oppId":   payload["oppId"],
                "value":   payload.get("value", 0),
                "summary": f"New opportunity: {payload.get('title')} (${payload.get('value', 0):,})",
                "simTime": sim_time,
                "severity": "info",
            })
            logger.info("Opportunity created", accountId=payload["accountId"], oppId=payload["oppId"], value=payload.get("value"))

        case "opportunity_stalled":
            days = payload.get("daysInStage", 0)
            state.upsert_opportunity(payload["accountId"], {
                "oppId":       payload["oppId"],
                "title":       payload.get("title", ""),
                "value":       payload.get("value", 0),
                "stage":       payload.get("stage", ""),
                "daysInStage": days,
                "stalledAt":   sim_time,
            })
            if days >= _STALL_DAYS:
                state.add_risk_flag(payload["accountId"], "quote_stalled")
                state.add_signal(payload["accountId"], {
                    "source":   "crm",
                    "type":     "opportunity_stalled",
                    "oppId":    payload["oppId"],
                    "value":    payload.get("value", 0),
                    "days":     days,
                    "summary":  f"Opp stalled {days}d — ${payload.get('value', 0):,} at risk",
                    "simTime":  sim_time,
                    "severity": "high",
                })
                state.recompute_health(payload["accountId"])
                logger.warn("Opportunity stalled", accountId=payload["accountId"], days=days)

        case "opportunity_risk_flagged":
            state.upsert_opportunity(payload["accountId"], {
                "oppId":      payload["oppId"],
                "value":      payload.get("value", 0),
                "riskType":   payload.get("riskType"),
                "riskDetail": payload.get("riskDetail"),
            })
            state.add_risk_flag(payload["accountId"], payload.get("riskType", "unknown_risk"))
            state.add_signal(payload["accountId"], {
                "source":   "crm",
                "type":     "opportunity_risk_flagged",
                "oppId":    payload["oppId"],
                "riskType": payload.get("riskType"),
                "summary":  f"Risk: {payload.get('riskDetail', '')}",
                "simTime":  sim_time,
                "severity": "high",
            })
            state.recompute_health(payload["accountId"])

        case "contact_sentiment_changed":
            state.upsert_contact(payload["accountId"], {
                "contactId": payload.get("contactId", ""),
                "name":      payload.get("contactName", ""),
                "role":      payload.get("role", ""),
                "sentiment": payload.get("toSentiment", "neutral"),
            })
            if payload.get("toSentiment") in ("cold", "negative"):
                state.add_risk_flag(payload["accountId"], "contact_cold")
                state.add_signal(payload["accountId"], {
                    "source":  "crm",
                    "type":    "contact_cold",
                    "contact": payload.get("contactName"),
                    "role":    payload.get("role"),
                    "summary": f"{payload.get('contactName')} ({payload.get('role')}) sentiment → {payload.get('toSentiment')}",
                    "simTime": sim_time,
                    "severity": "medium",
                })
                state.recompute_health(payload["accountId"])

        case "contact_updated":
            state.upsert_contact(payload["accountId"], {
                "contactId": payload.get("contactId", ""),
                "name":      payload.get("newValue") or payload.get("contactName", ""),
                "sentiment": payload.get("newSentiment", "neutral"),
            })

        case "contract_expiring":
            state.add_risk_flag(payload["accountId"], "contract_expiring")
            state.add_signal(payload["accountId"], {
                "source":     "crm",
                "type":       "contract_expiring",
                "contractId": payload.get("contractId"),
                "daysLeft":   payload.get("daysUntilExpiry"),
                "totalValue": payload.get("totalRemainingValue", 0),
                "summary":    f"Contract expires in {payload.get('daysUntilExpiry')}d — ${payload.get('totalRemainingValue', 0):,} at stake",
                "simTime":    sim_time,
                "severity":   "high",
            })
            state.recompute_health(payload["accountId"])
            logger.info("Contract expiring", accountId=payload["accountId"], daysLeft=payload.get("daysUntilExpiry"))

        case _:
            logger.debug("CRM: unhandled event type", type=t, eventId=event.get("eventId"))
