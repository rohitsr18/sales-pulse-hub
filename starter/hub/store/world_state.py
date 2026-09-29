"""In-memory account state machine. Single source of truth shared by all agents."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

class WorldState:
    def __init__(self) -> None:
        self._accounts: dict[str, dict[str, Any]] = {}
        self._supply:   dict[str, dict[str, Any]] = {}
        self._actions:  deque[dict[str, Any]]     = deque(maxlen=500)
        self._agent_activity: dict[str, dict[str, Any]] = {}

        # Subscribers for reactive agents (e.g. correlator)
        self._signal_listeners: list[asyncio.Queue[tuple[str, dict[str, Any]]]] = []

    # ── Agent activity ────────────────────────────────────────────

    def update_agent_activity(self, agent: str, action: str, cohort: str = "") -> None:
        existing = self._agent_activity.get(agent, {})
        self._agent_activity[agent] = {
            "agent":      agent,
            "lastAction": action,
            "lastAt":     datetime.now(tz=timezone.utc).isoformat(),
            "count":      existing.get("count", 0) + 1,
            "cohort":     cohort,
        }

    def get_agent_activity(self) -> list[dict[str, Any]]:
        return list(self._agent_activity.values())

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        return self._accounts.get(account_id)

    def upsert_account(self, account_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        base = self._accounts.get(account_id) or {
            "accountId":     account_id,
            "name":          "",
            "healthScore":   80,
            "riskFlags":     [],
            "opportunities": {},
            "contacts":      {},
            "signals":       [],
            "lastUpdated":   None,
        }
        base.update(patch)
        base["accountId"] = account_id
        self._accounts[account_id] = base
        return base

    def all_accounts(self) -> list[dict[str, Any]]:
        return list(self._accounts.values())

    def upsert_opportunity(self, account_id: str, opp: dict[str, Any]) -> None:
        acc = self._accounts.setdefault(account_id, self.upsert_account(account_id, {}))
        opps: dict[str, Any] = acc.setdefault("opportunities", {})
        opp_id = opp.get("oppId", "unknown")
        opps[opp_id] = {**opps.get(opp_id, {}), **opp}

    def upsert_contact(self, account_id: str, contact: dict[str, Any]) -> None:
        acc = self._accounts.get(account_id)
        if acc is None:
            return
        contacts: dict[str, Any] = acc.setdefault("contacts", {})
        cid = contact.get("contactId", f"c-{contact.get('name','x').lower().replace(' ','-')}")
        contacts[cid] = {**contacts.get(cid, {}), **contact}

    def add_risk_flag(self, account_id: str, flag: str) -> None:
        acc = self._accounts.get(account_id)
        if acc and flag not in acc["riskFlags"]:
            acc["riskFlags"].append(flag)

    def remove_risk_flag(self, account_id: str, flag: str) -> None:
        acc = self._accounts.get(account_id)
        if acc:
            acc["riskFlags"] = [f for f in acc["riskFlags"] if f != flag]

    def add_signal(self, account_id: str, signal: dict[str, Any]) -> None:
        acc = self._accounts.get(account_id)
        if acc is None:
            self.upsert_account(account_id, {})
            acc = self._accounts[account_id]
        signals: list[dict[str, Any]] = acc.setdefault("signals", [])
        signals.append(signal)
        # Keep latest 50 per account
        if len(signals) > 50:
            del signals[: len(signals) - 50]
        # Notify reactive listeners
        for q in self._signal_listeners:
            q.put_nowait((account_id, signal))

    def get_signals(self, account_id: str, limit: int = 20) -> list[dict[str, Any]]:
        acc = self._accounts.get(account_id)
        if acc is None:
            return []
        return acc.get("signals", [])[-limit:]

    def upsert_supply(self, product_id: str, info: dict[str, Any]) -> None:
        self._supply[product_id] = {**self._supply.get(product_id, {}), **info, "productId": product_id}

    def get_supply(self, product_id: str) -> dict[str, Any] | None:
        return self._supply.get(product_id)

    def all_supply(self) -> list[dict[str, Any]]:
        return list(self._supply.values())

    _FLAG_PENALTIES: dict[str, int] = {
        "competitor_active":  15,
        "quote_stalled":      10,
        "contact_cold":       12,
        "delivery_risk":       8,
        "contract_expiring":  10,
        "exec_change":         8,
    }

    def recompute_health(self, account_id: str) -> int:
        acc = self._accounts.get(account_id)
        if acc is None:
            return 80
        score = 80
        for flag in acc.get("riskFlags", []):
            score -= self._FLAG_PENALTIES.get(flag, 5)
        score = max(5, min(100, score))
        acc["healthScore"] = score
        return score

    def log_action(self, action: dict[str, Any]) -> None:
        self._actions.append(action)

    def recent_actions(self, limit: int = 20) -> list[dict[str, Any]]:
        items = list(self._actions)
        return list(reversed(items[-limit:]))

    def subscribe_signals(self) -> asyncio.Queue[tuple[str, dict[str, Any]]]:
        """Return a queue that receives (account_id, signal) tuples."""
        q: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._signal_listeners.append(q)
        return q

    def to_json(self) -> dict[str, Any]:
        return {
            "accounts": [
                {
                    **a,
                    "opportunities": list(a.get("opportunities", {}).values()),
                    "contacts":      list(a.get("contacts", {}).values()),
                }
                for a in self._accounts.values()
            ],
            "supply":        self.all_supply(),
            "actions":       self.recent_actions(100),   # enough to cover all agent outputs
            "agentActivity": self.get_agent_activity(),
        }

# Singleton — every module imports the same instance
state = WorldState()
