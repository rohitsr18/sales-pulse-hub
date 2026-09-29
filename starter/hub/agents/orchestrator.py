"""Orchestrator — wires all seven agents to their feed subscriptions and starts the correlator."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from hub.lib import logger
from hub.store.world_state import state
from hub.tools.feed_subscriber import subscribe

from hub.agents import (
    account_intelligence,
    sales_continuity,
    fastflow_quote,
    cross_sell_engine,
    buyer_movement,
    deal_velocity,
    supply_delivery,
    data_quality,
)
from hub.agents.field_intel import handle as field_intel_handle
from hub.agents.correlator import run as run_correlator
from hub.agents.crm_watcher import handle as crm_state_sync

_SIM_HOST = os.environ.get("SIM_HOST", "localhost")


async def _load_snapshot() -> None:
    """
    Prime WorldState from the CRM and Supply snapshots at startup.
    Ensures installed base, territory, tier, and inventory are available
    to agents before the SSE stream begins.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # CRM snapshot — accounts, installed base, open opportunities
        try:
            resp = await client.get(f"http://{_SIM_HOST}:7001/snapshot")
            resp.raise_for_status()
            for acc in resp.json().get("data", {}).get("accounts", []):
                state.upsert_account(acc["accountId"], {
                    "name":          acc.get("name", ""),
                    "healthScore":   acc.get("healthScore", 80),
                    "installedBase": acc.get("installedBase", []),
                    "repId":         acc.get("repId"),
                    "territory":     acc.get("territory"),
                    "tier":          acc.get("tier"),
                })
                for opp in acc.get("opportunities") or []:
                    state.upsert_opportunity(acc["accountId"], opp)
            logger.info("CRM snapshot loaded", accounts=len(resp.json().get("data", {}).get("accounts", [])))
        except Exception as exc:  # noqa: BLE001
            logger.warn("CRM snapshot unavailable", err=str(exc))

        # Supply snapshot — initial inventory and lead times
        try:
            resp = await client.get(f"http://{_SIM_HOST}:7005/snapshot")
            resp.raise_for_status()
            for item in resp.json().get("data", {}).get("inventory", []):
                state.upsert_supply(item["productId"], {
                    "available": item.get("available", 0),
                    "leadWeeks": item.get("leadWeeks", 0),
                })
            logger.info("Supply snapshot loaded", items=len(resp.json().get("data", {}).get("inventory", [])))
        except Exception as exc:  # noqa: BLE001
            logger.warn("Supply snapshot unavailable", err=str(exc))


async def _deferred_dq_scan() -> None:
    """
    Run a full-portfolio duplicate scan 15s after startup so all account_synced
    events (including rogue records like NL-0847B) have been processed first.
    """
    await asyncio.sleep(15.0)
    from difflib import SequenceMatcher  # noqa: PLC0415
    sim_time = "2026-02-06T08:00:00Z"   # approximate DQ scan time
    _already_flagged: set[str] = set()
    accts = state.all_accounts()
    for i, a in enumerate(accts):
        aid  = a["accountId"]
        aname = (a.get("name") or "").lower().strip()
        if not aname:
            continue
        for b in accts[i+1:]:
            bid   = b["accountId"]
            bname = (b.get("name") or "").lower().strip()
            if not bname:
                continue
            pair = tuple(sorted([aid, bid]))
            if pair in _already_flagged:
                continue
            if SequenceMatcher(None, aname, bname).ratio() >= 0.72:
                _already_flagged.add(pair)
                logger.warn("Deferred DQ scan: duplicate pair", id1=aid, id2=bid)
                from hub.agents._submit import emit  # noqa: PLC0415
                emit(
                    sim_time=sim_time,
                    agent="data_quality",
                    action="duplicate_account_flagged",
                    account_id=aid,
                    value=0.0,
                    reach=10,
                    reversible=False,
                    external=False,
                )
    logger.info("Deferred DQ scan complete", checked=len(accts))


async def start() -> None:
    """Launch all agents and the correlator. Runs indefinitely."""
    logger.info("Orchestrator starting — 7-agent hub")

    await _load_snapshot()

    async def on_crm(event: dict[str, Any]) -> None:
        await crm_state_sync(event)
        await sales_continuity.handle(event)
        await deal_velocity.handle(event)
        await account_intelligence.handle(event)
        await data_quality.handle(event)
        if event["type"] == "account_synced":
            await cross_sell_engine.handle(event)

    async def on_voice(event: dict[str, Any]) -> None:
        await field_intel_handle(event)

    async def on_quotes(event: dict[str, Any]) -> None:
        await fastflow_quote.handle(event)

    async def on_market(event: dict[str, Any]) -> None:
        await account_intelligence.handle(event)
        await buyer_movement.handle(event)

    async def on_supply(event: dict[str, Any]) -> None:
        await supply_delivery.handle(event)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(subscribe("crm",    on_crm),    name="sub-crm")
        tg.create_task(subscribe("voice",  on_voice),  name="sub-voice")
        tg.create_task(subscribe("quotes", on_quotes), name="sub-quotes")
        tg.create_task(subscribe("market", on_market), name="sub-market")
        tg.create_task(subscribe("supply", on_supply), name="sub-supply")
        tg.create_task(run_correlator(), name="correlator")
        tg.create_task(_deferred_dq_scan(), name="dq-scan")

    logger.info("Orchestrator stopped")
