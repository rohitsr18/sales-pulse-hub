"""Sales Continuity — CRM rep assignments → coverage-gap alerts, pipeline-at-risk, handoff briefs."""

from __future__ import annotations

from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "sales_continuity"

_HANDOFF_SYSTEM = (
    "You are a sales operations manager. Write a concise handoff brief (max 100 words) "
    "for an incoming rep taking over an account. Include: account context, open opportunities, "
    "key contacts, last activity, and the single most important next action. Plain English."
)

async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "owner_changed" | "rep_assignment_changed":
            await _handle_rep_change(payload, sim_time)

        case "opportunity_stalled":
            account_id = payload.get("accountId", "")
            acc = state.get_account(account_id)
            if acc and acc.get("repRecentlyChanged"):
                _emit_pipeline_at_risk(account_id, payload, sim_time)

        case "contract_expiring":
            account_id = payload.get("accountId", "")
            acc = state.get_account(account_id)
            if acc and acc.get("repRecentlyChanged"):
                emit(
                    sim_time=sim_time,
                    agent=_AGENT,
                    action="renewal_continuity_risk",
                    account_id=account_id,
                    value=float(payload.get("totalRemainingValue", 0)),
                    reach=1,
                    reversible=True,
                    external=False,
                    extra={"daysUntilExpiry": payload.get("daysUntilExpiry")},
                )

        case _:
            pass  # all other CRM events handled by other agents

async def _handle_rep_change(payload: dict[str, Any], sim_time: str) -> None:
    account_id = payload.get("accountId", "")
    old_rep    = payload.get("oldRepId") or payload.get("previousOwner")
    new_rep    = payload.get("newRepId") or payload.get("newOwner")

    if not (old_rep or new_rep):
        return  # not a rep-change event

    logger.info("Rep assignment changed", accountId=account_id, oldRep=old_rep, newRep=new_rep)

    # Mark account as recently changed (deterministic rule, no LLM)
    state.upsert_account(account_id, {"repRecentlyChanged": True, "currentRep": new_rep})
    state.add_risk_flag(account_id, "rep_transition")
    state.add_signal(account_id, {
        "source":  "crm",
        "type":    "rep_assignment_changed",
        "oldRep":  old_rep,
        "newRep":  new_rep,
        "summary": f"Rep changed: {old_rep} → {new_rep}",
        "simTime": sim_time,
        "severity": "high",
    })

    # Calculate pipeline at risk from open opps (rule, no LLM)
    acc  = state.get_account(account_id)
    opps = list((acc.get("opportunities") or {}).values()) if acc else []
    pipeline_at_risk = sum(o.get("value", 0) for o in opps if o.get("stage") not in ("closed_won", "closed_lost"))

    # Emit coverage-gap alert (LOW blast — internal)
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="rep_transition",
        account_id=account_id,
        value=pipeline_at_risk,
        reach=1,
        reversible=True,
        external=False,
        extra={"oldRep": old_rep, "newRep": new_rep, "openOpps": len(opps)},
    )

    # Also flag any OTHER accounts where the departing rep has open opportunities
    if old_rep:
        for other_acc in state.all_accounts():
            other_id = other_acc["accountId"]
            if other_id == account_id:
                continue
            other_opps = list((other_acc.get("opportunities") or {}).values())
            rep_opps = [o for o in other_opps
                        if o.get("repId") == old_rep
                        and o.get("stage") not in ("closed_won", "closed_lost")]
            if rep_opps:
                at_risk_val = sum(o.get("value", 0) for o in rep_opps)
                state.add_risk_flag(other_id, "rep_transition")
                emit(
                    sim_time=sim_time,
                    agent=_AGENT,
                    action="rep_transition",
                    account_id=other_id,
                    value=at_risk_val,
                    reach=1,
                    reversible=True,
                    external=False,
                    extra={"oldRep": old_rep, "newRep": None, "openOpps": len(rep_opps)},
                )

    # Generate handoff brief if new rep assigned (ONE LLM call)
    if new_rep and pipeline_at_risk > 0:
        brief = await _generate_handoff_brief(account_id, new_rep, opps, sim_time)
        emit(
            sim_time=sim_time,
            agent=_AGENT,
            action="handoff_brief_generated",
            account_id=account_id,
            value=pipeline_at_risk,
            reach=1,
            reversible=True,
            external=False,
            extra={"newRep": new_rep, "brief": brief},
        )

def _emit_pipeline_at_risk(account_id: str, opp_payload: dict[str, Any], sim_time: str) -> None:
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="pipeline_at_risk",
        account_id=account_id,
        opportunity_id=opp_payload.get("oppId"),
        value=float(opp_payload.get("value", 0)),
        reach=1,
        reversible=True,
        external=False,
        extra={"daysInStage": opp_payload.get("daysInStage"), "stage": opp_payload.get("stage")},
    )

async def _generate_handoff_brief(
    account_id: str,
    new_rep: str,
    opps: list[dict[str, Any]],
    sim_time: str,  # noqa: ARG001
) -> str:
    acc = state.get_account(account_id)
    name = acc.get("name", account_id) if acc else account_id
    opp_summary = "; ".join(f"{o.get('title','?')} (€{o.get('value',0):,})" for o in opps[:3])
    try:
        return await chat(
            messages=[
                {"role": "system", "content": _HANDOFF_SYSTEM},
                {"role": "user", "content":
                    f"Account: {name}\nNew rep: {new_rep}\n"
                    f"Open opportunities: {opp_summary or 'none'}\n"
                    "Write the handoff brief."},
            ],
            max_tokens=200,
            context="sales-continuity-handoff",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warn("Handoff brief generation failed", err=str(exc))
        return f"Handoff required for {name}. {len(opps)} open opportunities. New rep: {new_rep}."
