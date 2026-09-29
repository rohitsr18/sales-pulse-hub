"""SalesPulse Simulator entry point — starts all six feed servers and schedules events."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

import uvicorn

from sim import logger
from sim.clock import SimClock
from sim.events import EVENTS
from sim.validator import ValidationError, parse_seed, parse_speed

from sim.feeds.control import build_control_app
from sim.feeds.crm import build_crm_feed
from sim.feeds.voice import build_voice_feed
from sim.feeds.quotes import build_quotes_feed
from sim.feeds.market import build_market_feed
from sim.feeds.supply import build_supply_feed


# ── CLI / env configuration ────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SalesPulse Simulator")
    p.add_argument("--seed",    default=None)
    p.add_argument("--speed",   default=None)
    p.add_argument("--instant", action="store_true")
    return p.parse_args()


def _build_config() -> tuple[int, float, bool]:
    args = _parse_args()
    raw_seed  = os.environ.get("SIM_SEED")  or args.seed
    raw_speed = os.environ.get("SIM_SPEED") or args.speed
    instant   = os.environ.get("SIM_INSTANT", "").lower() == "true" or args.instant
    try:
        seed  = parse_seed(raw_seed)
        speed = parse_speed(raw_speed)
    except ValidationError as exc:
        logger.error("Invalid configuration", err=str(exc))
        sys.exit(1)
    return seed, speed, instant


# ── Event scheduling ────────────────────────────────────────────────────
async def _fire_when_due(
    event: dict,  # type: ignore[type-arg]
    clock: SimClock,
    feeds: dict,  # type: ignore[type-arg]
) -> None:
    delay = clock.seconds_until(event["simTime"])
    if delay > 0:
        await asyncio.sleep(delay)
    feed_fn = feeds.get(event["source"])
    if feed_fn is None:
        logger.warn("No feed for source", source=event["source"])
        return
    logger.info("Broadcasting event", eventId=event["eventId"], source=event["source"], type=event["type"])
    await feed_fn(event)


async def schedule_events(clock: SimClock, feeds: dict) -> None:  # type: ignore[type-arg]
    tasks = [asyncio.create_task(_fire_when_due(e, clock, feeds)) for e in EVENTS]
    await asyncio.gather(*tasks, return_exceptions=True)


# ── Main ────────────────────────────────────────────────────────────────
async def main() -> None:
    seed, speed, instant = _build_config()
    logger.info("SalesPulse starting", seed=seed, speed=speed, instant=instant)

    clock  = SimClock(speed=speed, instant=instant)
    config: dict = {"seed": seed}  # type: ignore[type-arg]

    # Build apps and broadcast callables
    control_app               = build_control_app(clock, config)
    crm_app,    crm_bcast     = build_crm_feed(clock)
    voice_app,  voice_bcast   = build_voice_feed(clock)
    quotes_app, quotes_bcast  = build_quotes_feed(clock)
    market_app, market_bcast  = build_market_feed(clock)
    supply_app, supply_bcast  = build_supply_feed(clock)

    feeds = {
        "crm":    crm_bcast,
        "voice":  voice_bcast,
        "quotes": quotes_bcast,
        "market": market_bcast,
        "supply": supply_bcast,
    }

    # Start all six uvicorn servers concurrently
    servers = [
        uvicorn.Server(uvicorn.Config(control_app, host="0.0.0.0", port=7000, log_level="warning")),
        uvicorn.Server(uvicorn.Config(crm_app,     host="0.0.0.0", port=7001, log_level="warning")),
        uvicorn.Server(uvicorn.Config(voice_app,   host="0.0.0.0", port=7002, log_level="warning")),
        uvicorn.Server(uvicorn.Config(quotes_app,  host="0.0.0.0", port=7003, log_level="warning")),
        uvicorn.Server(uvicorn.Config(market_app,  host="0.0.0.0", port=7004, log_level="warning")),
        uvicorn.Server(uvicorn.Config(supply_app,  host="0.0.0.0", port=7005, log_level="warning")),
    ]

    # Graceful shutdown — uvicorn.Server.should_exit is a plain bool
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: [setattr(s, "should_exit", True) for s in servers])

    async def _instant_events() -> None:
        """Instant mode: wait for clients to connect, then fire all events at once."""
        await asyncio.sleep(4.0)
        for event in EVENTS:
            bcast = feeds.get(event["source"])
            if bcast:
                await bcast(event)
        logger.info("Instant mode: all events dispatched", count=len(EVENTS))

    await asyncio.gather(
        *[s.serve() for s in servers],
        _instant_events() if instant else schedule_events(clock, feeds),
    )


if __name__ == "__main__":
    asyncio.run(main())
