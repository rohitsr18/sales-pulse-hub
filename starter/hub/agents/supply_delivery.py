"""Supply & Delivery Intelligence — Supply/Factory + CRM pipeline → delivery feasibility and alternative fulfilment. Feasibility is rule-based; one LLM call only when a constraint is detected and a refurb option exists."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "supply_delivery"

_ALT_SYSTEM = (
    "You are a supply chain analyst for medical imaging. "
    "A customer urgently needs equipment but the factory lead time exceeds their deadline. "
    "Propose the best alternative fulfilment option. "
    'Return JSON: {"proposedOption": str, "rationale": str, '
    '"riskLevel": "low"|"medium"|"high", "customerImpact": str, "confidence": float}'
)


async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "inventory_snapshot":
            for item in payload.get("items", []):
                state.upsert_supply(item["productId"], {
                    "available": item.get("available", 0),
                    "leadWeeks": item.get("leadWeeks", 0),
                })

        case "lead_time_extended":
            await _handle_lead_time_extension(payload, sim_time)

        case "refurb_units_available":
            product_id = payload["productId"]
            state.upsert_supply(product_id, {
                "refurbAvailable": payload.get("unitsAvailable", 0),
                "refurbLeadWeeks": payload.get("leadWeeks", 0),
                "refurbDiscount":  payload.get("priceDiscountPct", 0),
            })
            for acc in state.all_accounts():
                if "delivery_risk" in acc.get("riskFlags", []):
                    state.add_signal(acc["accountId"], {
                        "source":    "supply",
                        "type":      "refurb_available",
                        "productId": product_id,
                        "units":     payload.get("unitsAvailable"),
                        "leadWeeks": payload.get("leadWeeks"),
                        "discount":  payload.get("priceDiscountPct"),
                        "summary":   (
                            f"Refurb {product_id}: {payload.get('unitsAvailable')} units, "
                            f"{payload.get('leadWeeks')}w lead, {payload.get('priceDiscountPct')}% off"
                        ),
                        "simTime":   sim_time,
                        "severity":  "info",
                    })

        case "allocation_confirmed":
            account_id = payload.get("accountId", "")
            state.remove_risk_flag(account_id, "delivery_risk")
            state.add_signal(account_id, {
                "source":       "supply",
                "type":         "allocation_confirmed",
                "allocationId": payload.get("allocationId"),
                "summary":      f"Factory allocation confirmed for {account_id}",
                "simTime":      sim_time,
                "severity":     "info",
            })

        case _:
            pass


async def _handle_lead_time_extension(payload: dict[str, Any], sim_time: str) -> None:
    product_id = payload["productId"]
    new_weeks  = payload.get("newLeadWeeks", 0)
    prev_weeks = payload.get("previousLeadWeeks", 0)

    state.upsert_supply(product_id, {"leadWeeks": new_weeks, "extendedAt": sim_time})

    for acc in state.all_accounts():
        opps = acc.get("opportunities") or {}
        opps_list = list(opps.values()) if isinstance(opps, dict) else opps

        for opp in opps_list:
            if product_id not in (opp.get("products") or []):
                continue

            deadline_str = opp.get("deadline")
            constraint_detected = True
            if deadline_str:
                try:
                    sim_dt = datetime.fromisoformat(sim_time.replace("Z", "+00:00"))
                    deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                    constraint_detected = new_weeks > (deadline - sim_dt).days / 7
                except ValueError:
                    pass

            if not constraint_detected:
                continue

            account_id = acc["accountId"]
            state.add_risk_flag(account_id, "delivery_risk")
            state.recompute_health(account_id)

            # Signal for correlator cross-feed synthesis
            state.add_signal(account_id, {
                "source":    "supply",
                "type":      "delivery_constraint",
                "productId": product_id,
                "summary":   f"Delivery constraint: {product_id} lead {new_weeks}w exceeds deadline",
                "simTime":   sim_time,
                "severity":  "high",
            })

            emit(
                sim_time=sim_time,
                agent=_AGENT,
                action="delivery_constraint",
                account_id=account_id,
                opportunity_id=opp.get("oppId"),
                value=float(opp.get("value", 0)),
                reach=1,
                reversible=True,
                external=False,
                extra={
                    "productId":     product_id,
                    "newLeadWeeks":  new_weeks,
                    "prevLeadWeeks": prev_weeks,
                    "reason":        payload.get("reason"),
                },
            )

            supply = state.get_supply(f"{product_id}-REF") or state.get_supply(product_id)
            if supply and supply.get("refurbAvailable", 0) > 0:
                await _propose_alternative(account_id, opp, payload, supply, sim_time)
            else:
                logger.warn(
                    "Delivery constraint — no refurb available",
                    accountId=account_id,
                    productId=product_id,
                    newLeadWeeks=new_weeks,
                )


async def _propose_alternative(
    account_id: str,
    opp: dict[str, Any],
    payload: dict[str, Any],
    supply: dict[str, Any],
    sim_time: str,
) -> None:
    acc  = state.get_account(account_id)
    name = acc.get("name", account_id) if acc else account_id

    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _ALT_SYSTEM},
                {"role": "user", "content": (
                    f"Account: {name}\n"
                    f"Opportunity: {opp.get('title')} (€{opp.get('value', 0):,})\n"
                    f"Product: {payload['productId']}\n"
                    f"Factory lead: {payload.get('newLeadWeeks')}w (was {payload.get('previousLeadWeeks')}w)\n"
                    f"Deadline: {opp.get('deadline', 'not specified')}\n"
                    f"Refurb available: {supply.get('refurbAvailable', 0)} units, "
                    f"{supply.get('refurbLeadWeeks', '?')}w, {supply.get('refurbDiscount', 0)}% off\n"
                    "Propose the best option."
                )},
            ],
            max_tokens=300,
            json_mode=True,
            context="supply-alternative",
        )
        result = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warn("Alternative fulfilment proposal failed", err=str(exc))
        result = {
            "proposedOption": "certified_refurb",
            "rationale":      "Fastest available option",
            "riskLevel":      "medium",
            "customerImpact": "Price reduction offset by faster delivery",
            "confidence":     0.6,
        }

    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="alternative_fulfilment_proposed",
        account_id=account_id,
        opportunity_id=opp.get("oppId"),
        value=float(opp.get("value", 0)),
        reach=1,
        reversible=True,
        external=False,
        extra={
            "proposedOption": result.get("proposedOption"),
            "rationale":      result.get("rationale"),
            "riskLevel":      result.get("riskLevel"),
            "customerImpact": result.get("customerImpact"),
            "confidence":     result.get("confidence", 0.6),
        },
    )
