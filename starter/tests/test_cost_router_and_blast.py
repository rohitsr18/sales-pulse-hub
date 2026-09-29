"""Unit tests for cost_router and blast_radius."""

from __future__ import annotations

import pytest

from hub.tools.cost_router import needs_llm
from hub.tools.blast_radius import compute, cohort_from_account_id


# ── cost_router ─────────────────────────────────────────────────────────

class TestCostRouter:
    # Events that must NEVER trigger an LLM call
    @pytest.mark.parametrize("source,type_", [
        ("crm",    "account_synced"),
        ("crm",    "activity_logged"),
        ("crm",    "account_updated"),
        ("crm",    "contact_updated"),
        ("crm",    "stage_tick"),
        ("crm",    "email_logged"),
        ("crm",    "call_logged"),
        ("crm",    "owner_changed"),
        ("crm",    "opportunity_stalled"),
        ("crm",    "contract_expiring"),
        ("crm",    "opportunity_created"),
        ("crm",    "contact_sentiment_changed"),
        ("supply", "inventory_snapshot"),
        ("supply", "allocation_confirmed"),
        ("supply", "lead_time_extended"),
        ("supply", "refurb_units_available"),
    ])
    def test_no_llm_for_routine(self, source: str, type_: str) -> None:
        assert needs_llm({"source": source, "type": type_}) is False

    # Events that MUST trigger an LLM call
    @pytest.mark.parametrize("source,type_", [
        ("voice",  "voice_memo_received"),
        ("quotes", "inbound_quote_request"),
        ("quotes", "inbound_rfq"),
        ("market", "expansion_announcement"),
        ("market", "executive_change"),
        ("market", "competitor_activity"),
        ("market", "regulatory_funding"),
        ("market", "rfq_published"),
    ])
    def test_needs_llm_for_inference(self, source: str, type_: str) -> None:
        assert needs_llm({"source": source, "type": type_}) is True

    def test_unknown_event_is_safe_false(self) -> None:
        """Unknown events default to no LLM — fail-safe."""
        assert needs_llm({"source": "unknown", "type": "unknown_event"}) is False


# ── blast_radius ─────────────────────────────────────────────────────────

class TestBlastRadius:
    def test_external_irreversible_is_high(self) -> None:
        r = compute(value=1000, reversible=False, external=True)
        assert r["class"] == "high"
        assert r["_autonomy"] == "escalate"
        assert r["_deploymentStage"] == "act_with_approval"

    def test_large_reach_is_high(self) -> None:
        r = compute(value=0, reach=11, reversible=True, external=False)
        assert r["class"] == "high"

    def test_large_external_value_is_high(self) -> None:
        r = compute(value=2_500_000, external=True, reversible=True)
        assert r["class"] == "high"

    def test_medium_value_is_medium(self) -> None:
        r = compute(value=300_000, reversible=True, external=False)
        assert r["class"] == "medium"
        assert r["_autonomy"] == "recommend"
        assert r["_deploymentStage"] == "recommend"

    def test_external_reversible_is_medium(self) -> None:
        r = compute(value=50_000, reversible=True, external=True)
        assert r["class"] == "medium"

    def test_small_internal_reversible_is_low(self) -> None:
        r = compute(value=10_000, reach=1, reversible=True, external=False)
        assert r["class"] == "low"
        assert r["_autonomy"] == "act"
        assert r["_deploymentStage"] == "act_autonomous"

    def test_payload_preserves_inputs(self) -> None:
        r = compute(value=500_000, reach=3, reversible=False, external=False)
        assert r["value"] == 500_000
        assert r["reach"] == 3
        assert r["reversible"] is False
        assert r["external"] is False

    def test_blast_radius_not_equal_to_deal_size(self) -> None:
        """Small master-data write (reach=20) should be high even with tiny value."""
        r = compute(value=100, reach=20, reversible=True, external=False)
        assert r["class"] == "high"

    def test_large_internal_alert_is_low(self) -> None:
        """Large internal alert (stays in system) is at most medium blast."""
        r = compute(value=5_000_000, reach=1, reversible=True, external=False)
        # value > 200K → medium; but never high (no external, no irreversibility)
        assert r["class"] in ("low", "medium")
        assert r["class"] != "high"


class TestCohort:
    @pytest.mark.parametrize("account_id,expected", [
        ("NL-0847", "NL"),
        ("DE-0512", "DE"),
        ("UK-0199", "UK"),
        ("US-0234", "US"),
        ("SG-0156", "SG"),
    ])
    def test_cohort_from_account_id(self, account_id: str, expected: str) -> None:
        assert cohort_from_account_id(account_id) == expected
