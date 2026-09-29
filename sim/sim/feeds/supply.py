"""supply.py — Supply / Factory feed (port 7005)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sim.feed_base import build_feed_app

_WORLD = json.loads((Path(__file__).parents[2] / "data" / "world.json").read_text())

def build_supply_feed(clock: Any) -> tuple[Any, Any]:
    def _snapshot(_at: str) -> dict[str, Any]:
        return {
            "inventory": [
                {"productId": p["productId"], "name": p["name"], "leadWeeks": p["leadWeeks"], "available": 0}
                for p in _WORLD["products"]
            ]
        }

    return build_feed_app(
        source="supply",
        feed_name="Supply / Factory Feed",
        clock=clock,
        capabilities=["inventory_snapshot", "lead_time_extended", "refurb_units_available", "allocation_confirmed"],
        build_snapshot=_snapshot,
    )
