"""Data Quality — detects duplicate accounts, stale contacts, mislabelled stages, and orphaned records. Zero LLM calls; all checks are deterministic rules."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state

_AGENT = "data_quality"
_STALE_CONTACT_DAYS = 180
_DUPLICATE_THRESHOLD = 0.72  # SequenceMatcher ratio above which names are flagged

# Tracks reps marked as departed via owner_changed(reason=rep_departure)
_departed_reps: set[str] = set()


async def handle(event: dict[str, Any]) -> None:
    t = event["type"]
    p = event["payload"]
    sim_time = event["simTime"]

    match t:
        case "account_synced":
            _check_duplicate(p, sim_time)

        case "contact_updated":
            _check_stale_contact(p, sim_time)

        case "opportunity_created":
            _check_opportunity_fields(p, sim_time)

        case "opportunity_stalled":
            _check_orphaned_rep(p, sim_time)

        case "owner_changed":
            # Track rep departure so orphan detection works
            if p.get("reason") == "rep_departure":
                old = p.get("oldRepId") or p.get("previousOwner", "")
                if old:
                    _departed_reps.add(old)
                    logger.info("Rep marked departed", repId=old)

        case _:
            pass


def _check_duplicate(payload: dict[str, Any], sim_time: str) -> None:
    """Flag accounts whose names are suspiciously similar to an existing record."""
    new_id = payload.get("accountId", "")
    new_name = (payload.get("name") or "").lower().strip()
    if not new_name:
        return

    for existing in state.all_accounts():
        if existing["accountId"] == new_id:
            continue
        existing_name = (existing.get("name") or "").lower().strip()
        similarity = SequenceMatcher(None, new_name, existing_name).ratio()
        if similarity >= _DUPLICATE_THRESHOLD:
            logger.warn(
                "Possible duplicate account",
                newId=new_id,
                existingId=existing["accountId"],
                similarity=round(similarity, 2),
            )
            emit(
                sim_time=sim_time,
                agent=_AGENT,
                action="duplicate_account_flagged",
                account_id=new_id,
                value=0.0,
                reach=10,       # HIGH — master-data write touches every downstream agent
                reversible=False,
                external=False,
                extra={
                    "matchedAccountId": existing["accountId"],
                    "matchedName":      existing.get("name"),
                    "similarity":       round(similarity, 2),
                    "severity":         "high",
                },
            )
            break  # one alert per account_synced event is enough


def _check_stale_contact(payload: dict[str, Any], sim_time: str) -> None:
    """Flag contacts with no CRM activity for more than _STALE_CONTACT_DAYS days."""
    last_activity_str = payload.get("lastActivityDate")
    if not last_activity_str:
        return

    try:
        last_dt = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
        sim_dt  = datetime.fromisoformat(sim_time.replace("Z", "+00:00"))
        days_stale = (sim_dt - last_dt).days
    except ValueError:
        return

    if days_stale < _STALE_CONTACT_DAYS:
        return

    account_id = payload.get("accountId", "")
    logger.warn("Stale contact detected", accountId=account_id, days=days_stale, contactId=payload.get("contactId"))
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="stale_contact_detected",
        account_id=account_id,
        value=0.0,
        reach=1,
        reversible=True,
        external=False,
        extra={
            "contactId":   payload.get("contactId"),
            "contactName": payload.get("name"),
            "daysStale":   days_stale,
            "severity":    "medium",
        },
    )

    state.add_signal(account_id, {
        "source":  "data_quality",
        "type":    "data_quality_issue",
        "issue":   "stale_contact",
        "summary": f"Contact {payload.get('name')} stale {days_stale}d — verify or archive",
        "simTime": sim_time,
        "severity": "medium",
    })


def _check_opportunity_fields(payload: dict[str, Any], sim_time: str) -> None:
    """Detect mislabelled stages and missing required fields on new opportunities."""
    account_id = payload.get("accountId", "")
    opp_id     = payload.get("oppId", "")
    issues: list[str] = []

    # closed_won with no close date is a data entry error
    if payload.get("stage") == "closed_won" and not payload.get("closeDate"):
        issues.append("closed_won_without_close_date")

    # zero value on an open capital opportunity is almost certainly missing data
    if payload.get("value", 1) == 0 and payload.get("stage") not in ("closed_lost", "lost"):
        issues.append("zero_value_open_opportunity")

    if not issues:
        return

    for issue in issues:
        logger.warn("Opportunity data issue", oppId=opp_id, issue=issue)
        emit(
            sim_time=sim_time,
            agent=_AGENT,
            action="opportunity_data_issue",
            account_id=account_id,
            opportunity_id=opp_id,
            value=0.0,
            reach=1,
            reversible=True,
            external=False,
            extra={"issue": issue, "oppId": opp_id, "severity": "medium"},
        )

    state.add_signal(account_id, {
        "source":  "data_quality",
        "type":    "data_quality_issue",
        "issue":   issues[0],
        "summary": f"Opportunity {opp_id} has data issues: {', '.join(issues)}",
        "simTime": sim_time,
        "severity": "medium",
    })


def _check_orphaned_rep(payload: dict[str, Any], sim_time: str) -> None:
    """Flag stalled opportunities still assigned to a rep who has departed."""
    rep_id     = payload.get("repId", "")
    account_id = payload.get("accountId", "")
    opp_id     = payload.get("oppId", "")

    if rep_id not in _departed_reps:
        return

    logger.warn("Orphaned opportunity — departed rep", oppId=opp_id, repId=rep_id)
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="orphaned_opportunity_detected",
        account_id=account_id,
        opportunity_id=opp_id,
        value=float(payload.get("value", 0)),
        reach=1,
        reversible=True,
        external=False,
        extra={
            "departedRepId": rep_id,
            "oppId":         opp_id,
            "daysInStage":   payload.get("daysInStage"),
            "severity":      "high",
        },
    )

    state.add_signal(account_id, {
        "source":  "data_quality",
        "type":    "data_quality_issue",
        "issue":   "orphaned_opportunity",
        "summary": f"Opp {opp_id} assigned to departed rep {rep_id} — reassign immediately",
        "simTime": sim_time,
        "severity": "high",
    })
