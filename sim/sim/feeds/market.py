"""market.py — Market Signals feed (port 7004)."""

from __future__ import annotations

from typing import Any

from sim.feed_base import build_feed_app

def build_market_feed(clock: Any) -> tuple[Any, Any]:
    return build_feed_app(
        source="market",
        feed_name="Market Signals Feed",
        clock=clock,
        capabilities=[
            "expansion_announcement", "budget_cycle_open", "executive_change",
            "competitor_activity", "regulatory_funding", "rfq_published",
        ],
        build_snapshot=lambda _at: {"signals": []},
    )
