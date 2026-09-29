"""quotes.py — Quote Inbox feed (port 7003)."""

from __future__ import annotations

from typing import Any

from sim.feed_base import build_feed_app

def build_quotes_feed(clock: Any) -> tuple[Any, Any]:
    return build_feed_app(
        source="quotes",
        feed_name="Quote Inbox Feed",
        clock=clock,
        capabilities=["inbound_quote_request", "inbound_rfq"],
        build_snapshot=lambda _at: {"quotes": []},
    )
