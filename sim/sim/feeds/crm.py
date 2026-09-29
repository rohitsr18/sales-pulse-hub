"""crm.py — CRM feed (port 7001)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sim.feed_base import build_feed_app

_WORLD = json.loads((Path(__file__).parents[2] / "data" / "world.json").read_text())

def build_crm_feed(clock: Any) -> tuple[Any, Any]:
    def _snapshot(at: str) -> dict[str, Any]:
        return {"accounts": [{"snapshotAt": at, **a} for a in _WORLD["accounts"]]}

    return build_feed_app(
        source="crm",
        feed_name="CRM Feed",
        clock=clock,
        capabilities=[
            "account_synced", "opportunity_created", "opportunity_stalled",
            "opportunity_risk_flagged", "activity_logged", "contact_sentiment_changed",
            "contact_updated", "contract_expiring",
        ],
        build_snapshot=_snapshot,
    )
