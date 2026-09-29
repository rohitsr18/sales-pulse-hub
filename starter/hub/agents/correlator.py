"""Cross-agent synthesis — correlates signals from all feeds per account and classifies the scenario. Pattern matching is rule-based; one LLM call only when rule confidence is below 0.80."""
# NOTE: currently polls every 30s which is fine for the sim but would need to be
# event-driven in a real deployment — polling is just simpler to reason about here.

from __future__ import annotations

import asyncio
import json
from typing import Any

from hub.agents._submit import emit
from hub.lib import logger
from hub.store.world_state import state
from hub.tools.llm_client import chat

_CONF_THRESHOLD = 0.65

_PATTERNS: dict[str, dict[str, Any]] = {
    # Signal type → what agents actually write to WorldState via state.add_signal()
    "rep_transition":         {"required": {"rep_assignment_changed"},                "min": 1},
    "buyer_movement":         {"required": {"executive_change"},                      "min": 1},
    "expansion_announcement": {"required": {"expansion_detected"},                    "min": 1},
    "inbound_capital_quote":  {"required": {"capital_quote_received"},                "min": 1},
    "deal_stall":             {"required": {"deal_stall"},                            "min": 1},
    "delivery_constraint":    {"required": {"delivery_constraint"},                   "min": 1},
    "competitor_rfp":         {"required": {"competitor_threat", "deal_stall"},       "min": 2},
    "data_quality":           {"required": {"data_quality_issue"},                    "min": 2},
}

_SYNTHESIS_SYSTEM = (
    "You are the cross-agent synthesis layer. Given recent signals across all feeds for one "
    "hospital account, identify the primary scenario type and produce a brief recommendation. "
    'Return JSON: {"scenarioType": str, "confidence": float, "summary": str, '
    '"urgency": "low"|"normal"|"high"|"critical"}'
)


async def run() -> None:
    """Subscribe to WorldState signals and emit a submission entry for every cross-feed scenario detected."""
    signal_queue = state.subscribe_signals()
    recently_seen: dict[str, str] = {}

    logger.info("Correlator started")

    while True:
        account_id, _sig = await signal_queue.get()
        await asyncio.sleep(0.3)  # debounce burst

        signals = state.get_signals(account_id, limit=20)
        if len(signals) < 2:
            continue

        scenario = await _correlate(account_id, signals)
        if scenario is None:
            continue

        # Avoid re-emitting the same scenario for the same account unless confidence is very high
        if recently_seen.get(account_id) == scenario["scenarioType"] and scenario["confidence"] < 0.9:
            continue
        recently_seen[account_id] = scenario["scenarioType"]

        revenue = float(scenario.get("revenueAtStake", 0))
        sim_time = signals[-1].get("simTime", "") if signals else ""

        logger.info(
            "Cross-feed scenario detected",
            accountId=account_id,
            scenario=scenario["scenarioType"],
            confidence=scenario["confidence"],
        )

        emit(
            sim_time=sim_time,
            agent="correlator",
            action=f"cross_feed_{scenario['scenarioType']}",
            account_id=account_id,
            value=revenue,
            reach=1,
            reversible=True,
            external=False,
            extra={
                "scenarioType": scenario["scenarioType"],
                "confidence":   scenario["confidence"],
                "urgency":      scenario.get("urgency", "normal"),
                "summary":      scenario.get("summary", ""),
            },
        )

async def _correlate(account_id: str, signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    sig_types = {s.get("type", "") for s in signals}
    candidates: list[tuple[str, float]] = []

    for scenario, rules in _PATTERNS.items():
        required = rules["required"]
        hits = len(sig_types & required)
        if hits >= rules["min"]:
            conf = 0.60 + (hits / len(required)) * 0.25
            candidates.append((scenario, min(0.90, conf)))

    if not candidates:
        return None

    best_type, best_conf = max(candidates, key=lambda x: x[1])
    if best_conf < _CONF_THRESHOLD:
        return None

    if best_conf < 0.80:
        return await _llm_confirm(account_id, signals, best_type, best_conf)

    return {
        "scenarioType": best_type,
        "confidence":   best_conf,
        "summary":      f"Cross-feed: {best_type}",
        "urgency":      "high" if best_conf > 0.80 else "normal",
        "revenueAtStake": _estimate_revenue(signals),
    }

async def _llm_confirm(
    account_id: str,
    signals: list[dict[str, Any]],
    hint: str,
    base_conf: float,
) -> dict[str, Any] | None:
    summary = "\n".join(f"- [{s.get('source','?')}] {s.get('type','?')}: {s.get('summary','')}" for s in signals[-8:])
    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user",   "content": f"Account: {account_id}\nHint: {hint}\nSignals:\n{summary}"},
            ],
            max_tokens=250,
            json_mode=True,
            context="correlate",
        )
        result: dict[str, Any] = json.loads(raw)
        if result.get("confidence", 0) >= _CONF_THRESHOLD:
            result["revenueAtStake"] = _estimate_revenue(signals)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.warn("Correlator LLM call failed", err=str(exc))
    return {"scenarioType": hint, "confidence": base_conf, "summary": f"Correlation: {hint}", "urgency": "normal", "revenueAtStake": _estimate_revenue(signals)}

def _estimate_revenue(signals: list[dict[str, Any]]) -> float:
    for s in reversed(signals):
        for k in ("value", "totalValue", "estimatedValue", "amount"):
            v = s.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    return 0.0
