"""Rules-first LLM filter. Returns False for routine CRM/supply events (no LLM needed) and True only for events that require genuine inference."""

from __future__ import annotations
from typing import Any

_ROUTINE_CRM: frozenset[str] = frozenset({
    "account_synced",
    "activity_logged",
    "account_updated",
    "contact_updated",
    "stage_tick",
    "note_created",
    "task_created",
    "task_completed",
    "email_logged",
    "call_logged",
    "meeting_logged",
    "territory_updated",
    "forecast_category_changed",
    "owner_changed",          # data_quality and sales_continuity handle via rules
    "opportunity_stalled",
    "opportunity_risk_flagged",
    "contract_expiring",
    "opportunity_created",    # data_quality checks fields; deal_velocity tracks age
    "contact_sentiment_changed",
    "opportunity_stage_changed",
})

_ROUTINE_SUPPLY: frozenset[str] = frozenset({
    "inventory_snapshot",
    "allocation_confirmed",
    "factory_capacity_updated",
    "lead_time_extended",
    "refurb_units_available",
})

_NEEDS_LLM: frozenset[str] = frozenset({
    "voice_memo_received",
    "inbound_quote_request",
    "inbound_rfq",
    "expansion_announcement",
    "executive_change",
    "competitor_activity",
    "regulatory_funding",
    "rfq_published",
})

def needs_llm(event: dict[str, Any]) -> bool:
    """Return True only if this event requires LLM inference."""
    source = event.get("source", "")
    type_ = event.get("type", "")

    if source == "crm" and type_ in _ROUTINE_CRM:
        return False
    if source == "supply" and type_ in _ROUTINE_SUPPLY:
        return False
    if type_ in _NEEDS_LLM:
        return True
    return False
