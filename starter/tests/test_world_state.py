"""Unit tests for WorldState."""

from __future__ import annotations

import pytest

from hub.store.world_state import WorldState


@pytest.fixture()
def ws() -> WorldState:
    return WorldState()  # fresh instance per test


class TestUpsertAccount:
    def test_creates_account(self, ws: WorldState) -> None:
        acc = ws.upsert_account("NL-0847", {"name": "Erasmus MC"})
        assert acc["accountId"] == "NL-0847"
        assert acc["name"] == "Erasmus MC"
        assert acc["healthScore"] == 80  # default

    def test_patch_merges(self, ws: WorldState) -> None:
        ws.upsert_account("NL-0847", {"name": "Erasmus MC"})
        ws.upsert_account("NL-0847", {"healthScore": 65})
        acc = ws.get_account("NL-0847")
        assert acc is not None
        assert acc["name"] == "Erasmus MC"
        assert acc["healthScore"] == 65

    def test_get_returns_none_for_missing(self, ws: WorldState) -> None:
        assert ws.get_account("MISSING") is None

    def test_all_accounts_returns_list(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.upsert_account("A2", {})
        assert len(ws.all_accounts()) == 2


class TestRiskFlags:
    def test_add_flag(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.add_risk_flag("A1", "competitor_active")
        assert "competitor_active" in ws.get_account("A1")["riskFlags"]

    def test_no_duplicate_flags(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.add_risk_flag("A1", "quote_stalled")
        ws.add_risk_flag("A1", "quote_stalled")
        assert ws.get_account("A1")["riskFlags"].count("quote_stalled") == 1

    def test_remove_flag(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.add_risk_flag("A1", "contact_cold")
        ws.remove_risk_flag("A1", "contact_cold")
        assert "contact_cold" not in ws.get_account("A1")["riskFlags"]


class TestHealthScore:
    def test_score_decreases_with_flags(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.add_risk_flag("A1", "competitor_active")   # -15
        ws.add_risk_flag("A1", "quote_stalled")        # -10
        score = ws.recompute_health("A1")
        assert score == 55  # 80 - 15 - 10

    def test_floor_at_5(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        # Add six flags; total penalties = 15+10+12+8+10+8 = 63; 80-63 = 17
        for flag in ["competitor_active", "quote_stalled", "contact_cold", "delivery_risk", "contract_expiring", "exec_change"]:
            ws.add_risk_flag("A1", flag)
        score = ws.recompute_health("A1")
        assert score == 17  # floor is 5, but sum of penalties only reaches 63

    def test_floor_enforced(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        # Add many unknown flags to force score below floor
        for i in range(20):
            ws.add_risk_flag(f"A1", f"unknown_flag_{i}")
        score = ws.recompute_health("A1")
        assert score == 5  # floor clamped


class TestSignals:
    def test_signal_added(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.add_signal("A1", {"type": "test", "summary": "hello"})
        signals = ws.get_signals("A1")
        assert len(signals) == 1
        assert signals[0]["type"] == "test"

    def test_signal_capped_at_50(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        for i in range(60):
            ws.add_signal("A1", {"type": f"sig_{i}"})
        assert len(ws.get_signals("A1", limit=100)) == 50

    def test_missing_account_returns_empty(self, ws: WorldState) -> None:
        assert ws.get_signals("MISSING") == []


class TestOpportunity:
    def test_upsert_creates(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.upsert_opportunity("A1", {"oppId": "OPP-001", "value": 1_000_000})
        opps = ws.get_account("A1")["opportunities"]
        assert "OPP-001" in opps
        assert opps["OPP-001"]["value"] == 1_000_000

    def test_upsert_merges(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {})
        ws.upsert_opportunity("A1", {"oppId": "OPP-001", "value": 500_000})
        ws.upsert_opportunity("A1", {"oppId": "OPP-001", "stage": "proposal"})
        opp = ws.get_account("A1")["opportunities"]["OPP-001"]
        assert opp["value"] == 500_000
        assert opp["stage"] == "proposal"


class TestActionLog:
    def test_log_and_retrieve(self, ws: WorldState) -> None:
        ws.log_action({"eventId": "act_001", "action": "test"})
        ws.log_action({"eventId": "act_002", "action": "test2"})
        actions = ws.recent_actions(limit=10)
        assert len(actions) == 2
        # Most recent first
        assert actions[0]["eventId"] == "act_002"

    def test_capped_at_500(self, ws: WorldState) -> None:
        for i in range(510):
            ws.log_action({"eventId": f"act_{i}"})
        assert len(ws.recent_actions(limit=1000)) == 500


class TestSerialisation:
    def test_to_json_shape(self, ws: WorldState) -> None:
        ws.upsert_account("A1", {"name": "Test"})
        ws.upsert_opportunity("A1", {"oppId": "O1", "value": 100})
        result = ws.to_json()
        assert "accounts" in result
        assert "supply" in result
        assert "actions" in result
        acc = result["accounts"][0]
        assert isinstance(acc["opportunities"], list)
        assert isinstance(acc["contacts"], list)
