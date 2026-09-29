"""Hub FastAPI application — serves the dashboard, SSE state stream, and REST API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

from hub.lib import logger, quota
from hub.store.world_state import state

_DASHBOARD_DIR = Path(__file__).parent / "dashboard"

app = FastAPI(title="SalesPulse Hub", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
)

# SSE dashboard clients
_dashboard_clients: list[asyncio.Queue[dict[str, Any]]] = []


def broadcast_state() -> None:
    """Push the current world state to all connected dashboard clients."""
    payload = state.to_json()
    for q in list(_dashboard_clients):
        q.put_nowait(payload)


async def _broadcast_loop() -> None:
    """Push state to connected dashboard clients every 10 seconds (polled update)."""
    while True:
        await asyncio.sleep(10.0)
        if _dashboard_clients:
            broadcast_state()

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "svc": "hub"}

@app.get("/api/state")
async def api_state() -> JSONResponse:
    return JSONResponse(state.to_json())

@app.get("/api/actions")
async def api_actions(limit: int = 20) -> JSONResponse:
    return JSONResponse({"actions": state.recent_actions(limit)})

@app.get("/api/quota")
async def api_quota() -> JSONResponse:
    return JSONResponse(quota.summary())

@app.get("/api/agents")
async def api_agents() -> JSONResponse:
    """Live status of all seven agents — used by the agent strip."""
    return JSONResponse({"agents": state.get_agent_activity()})

@app.get("/api/safety")
async def api_safety() -> JSONResponse:
    """Rollout & safety panel data: blast breakdown, autonomy distribution, per-cohort."""
    actions = state.recent_actions(500)
    blast_counts: dict[str, int]   = {"low": 0, "medium": 0, "high": 0}
    autonomy_counts: dict[str, int] = {"act": 0, "recommend": 0, "escalate": 0}
    cohort_counts: dict[str, int]  = {}
    agent_counts: dict[str, int]   = {}
    unsafe = 0
    for a in actions:
        bc = (a.get("blastRadius") or {}).get("class", "")
        au = a.get("autonomy", "")
        co = a.get("cohort", "?")
        ag = a.get("agent", "?")
        if bc in blast_counts:    blast_counts[bc] += 1
        if au in autonomy_counts: autonomy_counts[au] += 1
        cohort_counts[co] = cohort_counts.get(co, 0) + 1
        agent_counts[ag]  = agent_counts.get(ag, 0) + 1
        if au == "escalate": unsafe += 1
    return JSONResponse({
        "totalActions":   len(actions),
        "blastCounts":    blast_counts,
        "autonomyCounts": autonomy_counts,
        "cohortCounts":   cohort_counts,
        "agentCounts":    agent_counts,
        "unsafeActions":  unsafe,
    })

_CHAT_SYSTEM_PROMPT = """You are SalesPulse, an AI sales-intelligence assistant embedded in a live B2B sales dashboard.
Answer questions concisely using ONLY the portfolio data provided.
Strict format rules:
- If the answer has multiple items: first line = short title ending with a colon, then each item on its own line starting with "•"
- If the answer is one sentence: just write that sentence (no title, no bullet)
- Keep the response under 120 words
- Use € for currency values (e.g. €2,400,000)
- Do NOT use markdown (no **, no ##, no backticks)
- Do NOT invent data; if something is unknown say so briefly"""


def _build_context() -> str:
    """Snapshot of current WorldState to ground the LLM response."""
    accts   = state.all_accounts()
    actions = state.recent_actions(500)
    risky   = [a for a in accts if a.get("riskFlags")]

    opps_of  = lambda a: list(a.get("opportunities", {}).values()) if isinstance(a.get("opportunities", {}), dict) else a.get("opportunities", [])
    pipeline = sum(sum(o.get("value", 0) for o in opps_of(a)) for a in accts)
    unsafe   = sum(1 for a in actions if a.get("autonomy") == "escalate")
    low      = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "low")
    med      = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "medium")
    high     = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "high")

    risky_lines = "\n".join(
        f"  {a['accountId']} health={a.get('healthScore', 80)} flags={', '.join(a.get('riskFlags', []))}"
        for a in sorted(risky, key=lambda x: x.get("healthScore", 80))[:6]
    ) or "  none"

    action_lines = "\n".join(
        f"  [{a.get('agent')}] {a.get('action')} → {(a.get('target') or {}).get('accountId', '?')}  €{(a.get('target') or {}).get('value', 0):,.0f}"
        for a in actions[:10]
    ) or "  none"

    stalls = [a for a in actions if a.get("action") == "deal_stall_detected"]
    stall_lines = "\n".join(
        f"  {(a.get('target') or {}).get('accountId','?')} €{(a.get('target') or {}).get('value',0):,.0f}"
        for a in stalls[:4]
    ) or "  none"

    agent_activity = "\n".join(
        f"  {a['agent']}: {a['count']} actions (last: {a['lastAction']})"
        for a in sorted(state.get_agent_activity(), key=lambda x: -x["count"])
    ) or "  none"

    return (
        f"Date: 2026-07-22\n"
        f"Accounts monitored: {len(accts)} across NL, DE, UK\n"
        f"Total pipeline: €{pipeline:,.0f}\n"
        f"At-risk accounts ({len(risky)}):\n{risky_lines}\n"
        f"Agent actions total: {len(actions)} (low blast: {low}, medium: {med}, high/escalated: {high}, unsafe: {unsafe})\n"
        f"Stalled deals:\n{stall_lines}\n"
        f"Recent agent actions:\n{action_lines}\n"
        f"Agent activity:\n{agent_activity}"
    )


async def _llm_chat(query: str) -> str | None:
    """Try LLM with a 9-second timeout. Returns None on any failure → caller uses rule-based fallback."""
    from hub.tools.llm_client import chat as llm_chat  # noqa: PLC0415
    try:
        context = _build_context()
        messages = [
            {"role": "system", "content": _CHAT_SYSTEM_PROMPT + "\n\nCURRENT PORTFOLIO DATA:\n" + context},
            {"role": "user", "content": query},
        ]
        result = await asyncio.wait_for(
            llm_chat(messages=messages, max_tokens=350, json_mode=False, context="chat", max_attempts=1),
            timeout=2.5,
        )
        text = (result or "").strip()
        return text if text else None
    except Exception as exc:
        logger.warn("LLM chat failed — using rule-based fallback", error=str(exc))
        return None


@app.post("/api/chat")
async def api_chat(request: Request) -> JSONResponse:
    """Answer a natural-language query — tries LLM first, falls back to rule-based."""
    body = await request.json()
    raw_query   = str(body.get("query", "")).strip()
    query_lower = raw_query.lower()

    response = await _llm_chat(raw_query)
    if not response:
        response = _chat_response(query_lower)

    return JSONResponse({"response": response, "query": raw_query})

def _chat_response(query: str) -> str:
    """Rule-based responses for dashboard and portfolio queries."""
    import re

    accts   = state.all_accounts()
    actions = state.recent_actions(500)
    risky   = [a for a in accts if a.get("riskFlags")]

    def _has(words: list[str]) -> bool:
        """Word-boundary match to avoid 'hi' hitting 'which', etc."""
        for w in words:
            pattern = r'\b' + re.escape(w) + r'\b' if len(w) <= 3 else w
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False

    # ── Greeting ──────────────────────────────────────────────────
    if _has(["hello", "hi", "hey", "howdy", "greetings", "sup", "yo",
             "good morning", "good afternoon", "good evening"]):
        count = len(risky)
        return (
            f"Hello! I'm the SalesPulse intelligence agent. "
            f"I'm monitoring {len(accts)} accounts across NL, DE, and UK — "
            f"currently {count} {'account is' if count == 1 else 'accounts are'} at risk. "
            f"How can I help you today?"
        )

    # ── Per-account health ────────────────────────────────────────
    acc_match = re.search(r'\b([A-Z]{2}-\d{3,})\b', query.upper())
    if acc_match:
        aid = acc_match.group(1)
        acc = state.get_account(aid)
        if acc:
            opps = list(acc.get("opportunities", {}).values()) if isinstance(acc.get("opportunities", {}), dict) else acc.get("opportunities", [])
            pipeline = sum(o.get("value", 0) for o in opps)
            sigs = len(acc.get("signals", []))
            return (
                f"{acc.get('name', aid)} ({aid})\n"
                f"• Health score: {acc.get('healthScore', 80)}\n"
                f"• Risk flags: {acc.get('riskFlags', []) or 'none'}\n"
                f"• Pipeline: €{pipeline:,.0f}\n"
                f"• Signals: {sigs}\n"
                f"• Territory: {acc.get('territory', '?')}"
            )
        return f"Account {aid} not found in WorldState."

    # ── KPIs ──────────────────────────────────────────────────────
    if _has(["kpi", "kpis", "metrics", "dashboard", "scorecard"]):
        opps_of = lambda a: list(a.get("opportunities",{}).values()) if isinstance(a.get("opportunities",{}),dict) else a.get("opportunities",[])
        pipeline = sum(sum(o.get("value",0) for o in opps_of(a)) for a in accts)
        at_risk_rev = sum(sum(o.get("value",0) for o in opps_of(a)) for a in risky)
        gaps = sum(1 for a in accts if "rep_transition" in a.get("riskFlags",[]))
        cs = sum((a.get("target") or {}).get("value",0) for a in actions if a.get("action") == "cross_sell_recommendation")
        unsafe = sum(1 for a in actions if a.get("autonomy") == "escalate")
        return (
            f"Live dashboard KPIs:\n"
            f"• Total pipeline:       €{pipeline:,.0f}\n"
            f"• At-risk revenue:      €{at_risk_rev:,.0f} ({len(risky)} accounts)\n"
            f"• Coverage gaps:        {gaps} accounts\n"
            f"• Cross-sell opps:      €{cs:,.0f}\n"
            f"• Total agent actions:  {len(actions)}\n"
            f"• Escalated to human:   {unsafe}"
        )

    # ── Actions / history ─────────────────────────────────────────
    if _has(["actions", "action", "what happened", "what was done", "history", "log"]):
        if not actions:
            return "No agent actions recorded yet."
        by_agent: dict = {}
        for a in actions:
            by_agent[a.get("agent","?")] = by_agent.get(a.get("agent","?"),0)+1
        lines = "\n".join(f"• {ag} — {n} actions" for ag, n in sorted(by_agent.items(), key=lambda x:-x[1]))
        recent = actions[:3]
        recent_txt = "\n".join(f"• [{a.get('agent')}] {a.get('action')} → {(a.get('target') or {}).get('accountId','?')}" for a in recent)
        return f"{len(actions)} total actions by agent:\n{lines}\nMost recent:\n{recent_txt}"

    # ── Scenarios detected ────────────────────────────────────────
    if _has(["scenario", "scenarios", "detected", "correlator", "cross-feed", "what found"]):
        corr = [a for a in actions if a.get("agent") == "correlator"]
        if not corr:
            return "No cross-feed scenarios detected yet."
        lines = "\n".join(
            f"  • {a.get('action','').replace('cross_feed_','').replace('_',' ').title()} — "
            f"{(a.get('target') or {}).get('accountId','?')} (€{(a.get('target') or {}).get('value',0):,.0f}, {a.get('autonomy','?')})"
            for a in corr
        )
        return f"{len(corr)} cross-feed scenarios detected by correlator:\n{lines}"

    # ── Agent status ──────────────────────────────────────────────
    if _has(["agent", "agents", "agent status", "agent strip", "who is working"]):
        activity = state.get_agent_activity()
        if not activity:
            return "No agent activity recorded yet."
        lines = "\n".join(
            f"• {a['agent']} — {a['count']} actions — last: {a['lastAction']}"
            for a in sorted(activity, key=lambda x: -x["count"])
        )
        return f"Agent activity ({len(activity)} active agents):\n{lines}"

    # ── Cohort breakdown ──────────────────────────────────────────
    if _has(["cohort", "market", "country", "nl", "de", "uk", "by country"]):
        cohort_actions: dict = {}
        cohort_risk: dict = {}
        for a in actions:
            co = a.get("cohort","?")
            cohort_actions[co] = cohort_actions.get(co, 0) + 1
        for acc in accts:
            co = acc.get("accountId","?")[:2]
            if acc.get("riskFlags"):
                cohort_risk[co] = cohort_risk.get(co, 0) + 1
        lines = []
        for co in sorted(set(list(cohort_actions)+list(cohort_risk))):
            lines.append(f"  {co}: {cohort_actions.get(co,0)} actions, {cohort_risk.get(co,0)} at-risk accounts")
        return "Breakdown by market cohort:\n" + "\n".join(lines)

    # ── At-risk ───────────────────────────────────────────────────
    if _has(["at risk", "at-risk", "risky", "danger", "worst"]):
        if not risky:
            return "No accounts currently at risk."
        lines = []
        for a in sorted(risky, key=lambda x: x.get("healthScore", 80))[:5]:
            flags = ", ".join(a.get("riskFlags", [])) or "none"
            lines.append(f"• {a['accountId']} ({a.get('name','?')}) — health {a.get('healthScore',80)} — {flags}")
        return f"{len(risky)} at-risk accounts:\n" + "\n".join(lines)

    # ── Stalled deals ─────────────────────────────────────────────
    if _has(["stall", "stuck", "deal velocity", "30 day", "30-day", "stalled"]):
        stalls = [a for a in actions if a.get("action") == "deal_stall_detected"]
        if not stalls:
            return "No stalled deals detected in this run."
        return f"{len(stalls)} stalled deals:\n" + "\n".join(
            f"  • {(a.get('target') or {}).get('accountId','?')} — €{(a.get('target') or {}).get('value',0):,.0f}" for a in stalls[:5])

    # ── Delivery / supply ─────────────────────────────────────────
    if _has(["delivery", "supply", "refurb", "lead time", "factory", "constraint"]):
        dcs = [a for a in actions if a.get("action") == "delivery_constraint_detected"]
        if not dcs:
            return "No delivery constraints detected."
        return f"{len(dcs)} delivery constraints:\n" + "\n".join(
            f"  • {(a.get('target') or {}).get('accountId','?')} — €{(a.get('target') or {}).get('value',0):,.0f}" for a in dcs[:5])

    # ── Pipeline / revenue ────────────────────────────────────────
    if _has(["pipeline", "revenue", "value", "total"]):
        opps_of = lambda a: list(a.get("opportunities",{}).values()) if isinstance(a.get("opportunities",{}),dict) else a.get("opportunities",[])
        total = sum(sum(o.get("value",0) for o in opps_of(a)) for a in accts)
        return f"Total tracked pipeline: €{total:,.0f} across {len(accts)} accounts."

    # ── Cross-sell ────────────────────────────────────────────────
    if _has(["cross-sell", "crosssell", "cross sell", "upsell", "cross sell"]):
        cs = [a for a in actions if a.get("action") == "cross_sell_recommendation"]
        total = sum((a.get("target") or {}).get("value",0) for a in cs)
        return f"{len(cs)} cross-sell recommendations totalling €{total:,.0f}."

    # ── Rep / coverage ────────────────────────────────────────────
    if _has(["rep", "coverage gap", "transition", "handoff", "departure"]):
        rts = [a for a in actions if "rep" in a.get("action","") or "coverage" in a.get("action","")]
        return f"{len(rts)} rep-transition actions detected." if rts else "No rep transitions detected."

    # ── FastFlow / quotes ─────────────────────────────────────────
    if _has(["quote", "fastflow", "capital", "consumable", "rfq"]):
        quotes = [a for a in actions if a.get("agent") == "fastflow"]
        v1 = sum(1 for q in quotes if "consumable" in q.get("action",""))
        v2 = sum(1 for q in quotes if "capital" in q.get("action",""))
        return f"FastFlow processed {len(quotes)} quotes ({v1} consumable auto-quoted, {v2} capital configured)."

    # ── Safety / governance ───────────────────────────────────────
    if _has(["safe", "blast", "autonomy", "escalat", "govern", "unsafe", "high blast"]):
        unsafe = sum(1 for a in actions if a.get("autonomy") == "escalate")
        low    = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "low")
        med    = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "medium")
        high   = sum(1 for a in actions if (a.get("blastRadius") or {}).get("class") == "high")
        return (
            f"Safety summary: {len(actions)} total actions\n"
            f"  • Low blast (act autonomous): {low}\n"
            f"  • Medium blast (recommend):   {med}\n"
            f"  • High blast (escalate):      {high}\n"
            f"  • Escalated to human:         {unsafe}"
        )

    # ── Summary / overview ────────────────────────────────────────
    if _has(["summary", "summarise", "summarize", "overview", "portfolio", "status", "brief", "how are we", "how is"]):
        unsafe = sum(1 for a in actions if a.get("autonomy") == "escalate")
        opps_of = lambda a: list(a.get("opportunities",{}).values()) if isinstance(a.get("opportunities",{}),dict) else a.get("opportunities",[])
        pipeline = sum(sum(o.get("value",0) for o in opps_of(a)) for a in accts)
        return (
            f"Portfolio overview:\n"
            f"  • {len(accts)} accounts monitored (NL/DE/UK)\n"
            f"  • {len(risky)} accounts at risk\n"
            f"  • €{pipeline:,.0f} total pipeline\n"
            f"  • {len(actions)} agent actions taken\n"
            f"  • {unsafe} require human approval\n"
            f"  Worst account: {risky[0]['accountId'] if risky else 'none'} "
            f"(health {risky[0].get('healthScore',80) if risky else '-'})"
        )

    return (
        "I can help with: at-risk accounts, KPIs, account health (e.g. 'NL-0847'), "
        "scenarios detected, agent status, stalled deals, delivery constraints, "
        "cross-sell opportunities, FastFlow quotes, safety summary, or portfolio overview. "
        "Try: 'What are the KPIs?' or 'Which scenarios were detected?'"
    )

@app.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _dashboard_clients.append(q)
    logger.info("Dashboard client connected", total=len(_dashboard_clients))

    async def _gen() -> AsyncGenerator[dict[str, Any], None]:
        # Send initial state on connect
        yield {"event": "state", "data": json.dumps(state.to_json())}
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    snapshot = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {"event": "state", "data": json.dumps(snapshot)}
                except asyncio.TimeoutError:
                    yield {"comment": "heartbeat"}
        finally:
            if q in _dashboard_clients:
                _dashboard_clients.remove(q)
            logger.info("Dashboard client disconnected", total=len(_dashboard_clients))

    return EventSourceResponse(_gen())

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_DASHBOARD_DIR / "index.html")

@app.get("/dashboard/{path:path}")
async def static(path: str) -> FileResponse:
    # Prevent directory traversal — only serve files inside dashboard/
    target = (_DASHBOARD_DIR / path).resolve()
    if not str(target).startswith(str(_DASHBOARD_DIR.resolve())):
        return FileResponse(_DASHBOARD_DIR / "index.html")  # 404 fallback
    if target.exists():
        return FileResponse(target)
    return FileResponse(_DASHBOARD_DIR / "index.html")

@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_broadcast_loop())
    logger.info("Hub server started on port 3000")

@app.on_event("shutdown")
async def _shutdown() -> None:
    from hub.tools.submission_writer import close  # noqa: PLC0415
    close()
    logger.info("Hub server stopped")
