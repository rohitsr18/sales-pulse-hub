"""FastFlow Quote — v1 auto-quotes consumables (zero LLM); v2 parses capital emails (one LLM call) and routes to the correct approver tier."""

from __future__ import annotations

from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.skills.parse_quote import parse_quote
from hub.store.world_state import state

_AGENT = "fastflow_quote"
_CONSUMABLE_KEYWORDS = frozenset({
    "contrast", "agent", "disposable", "glove", "catheter", "needle",
    "reagent", "film", "pad", "electrode", "gel", "dressing", "pack",
    "supply", "consumable", "single-use", "single use",
})

_CAPITAL_KEYWORDS = frozenset({
    "mri", "ct", "scanner", "system", "ingenia", "spectral", "azurion",
    "epiq", "intellivue", "pacs", "intellispace", "refurb", "magnet",
    "gantry", "1.5t", "3t", "interventional",
})
def _approver_tier(value: float) -> str:
    if value >= 2_000_000: return "vp"
    if value >= 500_000:   return "senior_manager"
    if value >= 100_000:   return "manager"
    return "auto_approve"

def _classify_tier(subject: str, body: str) -> str:
    """Rule-based tier classification — NO LLM call."""
    text = (subject + " " + body).lower()
    capital_hits    = sum(1 for k in _CAPITAL_KEYWORDS    if k in text)
    consumable_hits = sum(1 for k in _CONSUMABLE_KEYWORDS if k in text)
    return "capital" if capital_hits >= consumable_hits else "consumable"

async def handle(event: dict[str, Any]) -> None:
    if event["type"] not in ("inbound_quote_request", "inbound_rfq"):
        return

    payload    = event["payload"]
    account_id = payload.get("accountId", "")
    subject    = str(payload.get("subject", ""))
    body       = str(payload.get("body", ""))
    sim_time   = event["simTime"]

    tier = _classify_tier(subject, body)
    logger.info("FastFlow quote received", accountId=account_id, tier=tier, type=event["type"])

    if tier == "consumable":
        await _handle_v1(account_id, payload, sim_time)
    else:
        await _handle_v2(account_id, payload, sim_time)

async def _handle_v1(account_id: str, payload: dict[str, Any], sim_time: str) -> None:
    """
    FastFlow v1 — consumable auto-quote.
    Pure rule-based: no LLM, zero tokens, instant execution.
    """
    estimated_value = 15_000.0  # default for consumable bundles
    logger.info("FastFlow v1 auto-quoting consumable", accountId=account_id)

    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="inbound_consumable_quote",
        account_id=account_id,
        value=estimated_value,
        currency="EUR",
        reach=1,
        reversible=False,   # quote is sent to customer
        external=True,
        extra={"path": "v1", "approverTier": "auto_approve", "llmCalls": 0},
    )

async def _handle_v2(account_id: str, payload: dict[str, Any], sim_time: str) -> None:
    """
    FastFlow v2 — capital quote.
    ONE LLM call to parse the free-text email, then rule-based CPQ + routing.
    """
    logger.info("FastFlow v2 parsing capital quote", accountId=account_id)

    # ONE LLM call — parsing the free-text email body
    parsed = await parse_quote(payload)
    value  = float(parsed.get("estimatedValue") or 0)

    # CPQ configuration (rule-based, no LLM)
    approver = _approver_tier(value)
    products = [p.get("name", "?") for p in parsed.get("products", [])]

    # Create/update opportunity in WorldState
    if value > 0:
        state.upsert_opportunity(account_id, {
            "oppId":     f"FF-{account_id}-{sim_time[:10]}",
            "title":     payload.get("subject", "FastFlow Capital Quote"),
            "value":     value,
            "stage":     "rfq_received",
            "products":  [p.get("productId") or p.get("name") for p in parsed.get("products", [])],
            "deadline":  parsed.get("deadline"),
        })

    # Signal for correlator cross-feed synthesis
    state.add_signal(account_id, {
        "source":   "quotes",
        "type":     "capital_quote_received",
        "value":    value,
        "summary":  f"Capital quote received: {', '.join(products)} (€{value:,})",
        "simTime":  sim_time,
        "severity": "high",
    })

    # HIGH blast when routing to VP (external, irreversible commitment)
    is_vp_tier = approver == "vp"
    emit(
        sim_time=sim_time,
        agent=_AGENT,
        action="inbound_capital_quote",
        account_id=account_id,
        value=value,
        currency="EUR",
        reach=1,
        reversible=False,
        external=True,
        extra={
            "path":         "v2",
            "approverTier": approver,
            "products":     products,
            "tenderRef":    parsed.get("tenderRef"),
            "llmCalls":     1,
        },
    )

    logger.info(
        "FastFlow v2 quote configured",
        accountId=account_id,
        value=value,
        approver=approver,
        products=products,
    )
