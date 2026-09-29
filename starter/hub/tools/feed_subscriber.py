"""Async SSE subscriber for all five data feeds. Parses the wire format and dispatches events to handlers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from hub.lib import logger

SIM_HOST: str = __import__("os").environ.get("SIM_HOST", "localhost")

FEED_PORTS: dict[str, int] = {
    "crm":    7001,
    "voice":  7002,
    "quotes": 7003,
    "market": 7004,
    "supply": 7005,
}

_REQUIRED = frozenset({"eventId", "simTime", "seq", "source", "type", "version", "payload"})
_RECONNECT_DELAY = 5.0  # seconds before reconnecting after a drop

async def subscribe(
    feed_name: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    sim_host: str = SIM_HOST,
) -> None:
    """
    Connect to *feed_name* and call *handler* for every valid event.
    Automatically reconnects on connection drops.
    Never raises — all errors are logged.
    """
    port = FEED_PORTS.get(feed_name)
    if port is None:
        raise ValueError(f"Unknown feed: {feed_name!r}")

    url = f"http://{sim_host}:{port}/stream"

    while True:  # reconnect loop
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
                async with client.stream("GET", url) as response:
                    logger.info("Feed subscribed", feed=feed_name, url=url)
                    await _read_stream(feed_name, response, handler)
        except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            logger.warn(
                "Feed connection lost — reconnecting",
                feed=feed_name,
                err=str(exc),
                delay=_RECONNECT_DELAY,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected subscriber error", feed=feed_name, err=str(exc))

        await asyncio.sleep(_RECONNECT_DELAY)

async def _read_stream(
    feed_name: str,
    response: httpx.Response,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    """Parse raw SSE lines and dispatch to handler."""
    event_type = "message"
    data_buf = ""

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip()

        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_buf = line[5:].strip()
        elif line.startswith(":"):
            pass  # heartbeat comment — ignore
        elif line == "":
            if data_buf:
                _dispatch(feed_name, data_buf, event_type, handler)
            data_buf = ""
            event_type = "message"

def _dispatch(
    feed_name: str,
    raw: str,
    event_type: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        logger.warn("Malformed SSE message", feed=feed_name, data=raw[:120])
        return

    # The "connected" handshake has a different shape — skip validation
    if "feed" in event and "eventId" not in event:
        return

    missing = _REQUIRED - event.keys()
    if missing:
        logger.warn("Incomplete event envelope", feed=feed_name, missing=list(missing))
        return

    asyncio.ensure_future(
        _safe_call(handler, event, feed_name)
    )

async def _safe_call(
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    event: dict[str, Any],
    feed_name: str,
) -> None:
    try:
        await handler(event)
    except Exception as exc:  # noqa: BLE001
        logger.error("Agent handler threw", feed=feed_name, eventId=event.get("eventId"), err=str(exc))
