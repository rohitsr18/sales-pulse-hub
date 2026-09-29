"""Cross-Sell Engine — installed base + affinity table → recommendations. Affinity matching is rule-based; LLM only for high-value briefs (>€500K)."""

from __future__ import annotations

from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_AGENT = "cross_sell_engine"
# Affinity table: installed product → [(recommended, est. value, rationale)]
# TODO: load this from /meta or a config file rather than hardcoding
_AFFINITY: dict[str, list[tuple[str, float, str]]] = {
    "ING-1.5T":  [("ING-3T", 1_400_000, "Upgrade to 3T for advanced neuro/cardiac"),
                  ("COIL-NV", 180_000,   "Neurovascular coil upgrade for existing 1.5T")],
    "ING-3T":    [("SVC-ELITE", 450_000, "5-yr Elite service at renewal"),
                  ("COIL-NV",   180_000, "Neurovascular coil package")],
    "SCT-7500":  [("ING-3T",   1_400_000, "MRI complement for CT-heavy portfolio"),
                  ("SVC-ELITE", 220_000,  "CT service contract renewal")],
    "EPIQ-ELITE":[("SVC-ELITE", 90_000,  "Ultrasound service contract"),
                  ("ING-1.5T",  850_000, "MRI to complement ultrasound portfolio")],
    "AZU-IX":    [("SCT-7500", 1_100_000, "Spectral CT for interventional suite")],
}

_BRIEF_SYSTEM = (
    "You are a cross-sell specialist for medical imaging. "
    "Write a concise (max 80 words) recommendation brief for a sales rep. "
    "Explain why the recommended product fits the account's installed base and clinical profile."
)

async def handle(event: dict[str, Any]) -> None:
    t        = event["type"]
    payload  = event["payload"]
    sim_time = event["simTime"]

    # Only act on account syncs that carry installed base data
    if t not in ("account_synced",):
        return

    account_id  = payload.get("accountId", "")
    acc         = state.get_account(account_id)
    if acc is None:
        return

    installed = [item.get("productId", "") for item in acc.get("installedBase", [])]
    if not installed:
        return

    recommendations = _match_affinity(installed)
    if not recommendations:
        return

    # Emit recommendations — rule-based, low blast, no LLM
    for rec in recommendations:
        product, est_value, rationale = rec
        emit(
            sim_time=sim_time,
            agent=_AGENT,
            action="cross_sell_recommendation",
            account_id=account_id,
            value=est_value,
            currency="EUR",
            reach=1,
            reversible=True,
            external=False,
            extra={"recommendedProduct": product, "rationale": rationale, "llmBrief": None},
        )

    # ONE LLM call for high-value accounts to generate a polished narrative
    top_value = max(r[1] for r in recommendations)
    if top_value >= 500_000:
        top_rec = max(recommendations, key=lambda r: r[1])
        brief = await _generate_brief(account_id, installed, top_rec, sim_time)
        if brief:
            state.add_signal(account_id, {
                "source":  "cross_sell",
                "type":    "cross_sell_brief_ready",
                "summary": brief[:200],
                "simTime": sim_time,
                "severity": "info",
            })

def _match_affinity(installed: list[str]) -> list[tuple[str, float, str]]:
    """Pure rule: look up installed products in the affinity table."""
    seen_products: set[str] = set(installed)
    results: list[tuple[str, float, str]] = []
    for product in installed:
        for rec_product, value, rationale in _AFFINITY.get(product, []):
            if rec_product not in seen_products:
                results.append((rec_product, value, rationale))
                seen_products.add(rec_product)
    return results

async def _generate_brief(
    account_id: str,
    installed: list[str],
    top_rec: tuple[str, float, str],
    sim_time: str,  # noqa: ARG001
) -> str | None:
    acc = state.get_account(account_id)
    name = acc.get("name", account_id) if acc else account_id
    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _BRIEF_SYSTEM},
                {"role": "user", "content":
                    f"Account: {name}\nInstalled: {', '.join(installed)}\n"
                    f"Recommended: {top_rec[0]}\nRationale: {top_rec[2]}\n"
                    "Write the brief."},
            ],
            max_tokens=150,
            context="cross-sell-brief",
        )
        return raw
    except Exception as exc:  # noqa: BLE001
        logger.warn("Cross-sell brief failed", err=str(exc))
        return None
