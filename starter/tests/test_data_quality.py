"""Unit tests for the data_quality agent."""

from __future__ import annotations

import pytest

from hub.agents import data_quality as dq
from hub.store.world_state import WorldState


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a clean WorldState and an empty departed-reps set."""
    ws = WorldState()
    monkeypatch.setattr("hub.agents.data_quality.state", ws)
    monkeypatch.setattr("hub.agents.data_quality._departed_reps", set())


def _mk_event(type_: str, payload: dict, sim_time: str = "2026-02-10T09:00:00Z") -> dict:
    return {"type": type_, "payload": payload, "simTime": sim_time, "source": "crm",
            "eventId": "evt_test", "seq": 1, "version": "1.0"}


class TestDuplicateDetection:
    @pytest.mark.asyncio
    async def test_flags_similar_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ws = WorldState()
        # "Erasmus MC Rotterdam" vs "Erasmus MC Rotterdam UMC" — clearly >80% similar
        ws.upsert_account("NL-0847", {"name": "Erasmus MC Rotterdam"})
        monkeypatch.setattr("hub.agents.data_quality.state", ws)

        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        monkeypatch.setattr("hub.agents._submit.state", ws)

        event = _mk_event("account_synced", {
            "accountId": "NL-0847B",
            "name": "Erasmus MC Rotterdam UMC",  # >90% similar to NL-0847
            "healthScore": 70,
        })
        await dq.handle(event)
        actions = [e["action"] for e in emitted]
        assert "duplicate_account_detected" in actions

    @pytest.mark.asyncio
    async def test_no_flag_for_distinct_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ws = WorldState()
        ws.upsert_account("NL-0847", {"name": "Erasmus MC Rotterdam"})
        monkeypatch.setattr("hub.agents.data_quality.state", ws)

        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        monkeypatch.setattr("hub.agents._submit.state", ws)

        event = _mk_event("account_synced", {
            "accountId": "UK-0101",
            "name": "Manchester University NHS Foundation Trust",
            "healthScore": 80,
        })
        await dq.handle(event)
        actions = [e["action"] for e in emitted]
        assert "duplicate_account_detected" not in actions

    @pytest.mark.asyncio
    async def test_no_self_comparison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Re-syncing the same account ID should never flag itself."""
        ws = WorldState()
        ws.upsert_account("NL-0847", {"name": "Erasmus MC Rotterdam"})
        monkeypatch.setattr("hub.agents.data_quality.state", ws)

        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        monkeypatch.setattr("hub.agents._submit.state", ws)

        await dq.handle(_mk_event("account_synced", {"accountId": "NL-0847", "name": "Erasmus MC Rotterdam"}))
        assert not emitted


class TestStaleContact:
    @pytest.mark.asyncio
    async def test_flags_contact_over_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ws = WorldState()
        ws.upsert_account("UK-0101", {})
        monkeypatch.setattr("hub.agents.data_quality.state", ws)

        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        monkeypatch.setattr("hub.agents._submit.state", ws)

        await dq.handle(_mk_event("contact_updated", {
            "accountId": "UK-0101",
            "contactId": "C-011",
            "name": "Dr. C. Patel",
            "lastActivityDate": "2025-07-01T00:00:00Z",  # ~224 days before Feb 11
        }, sim_time="2026-02-11T09:00:00Z"))

        actions = [e["action"] for e in emitted]
        assert "stale_contact_detected" in actions

    @pytest.mark.asyncio
    async def test_no_flag_for_recent_contact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))

        await dq.handle(_mk_event("contact_updated", {
            "accountId": "UK-0101",
            "lastActivityDate": "2026-01-15T00:00:00Z",  # only 27 days ago
        }, sim_time="2026-02-11T09:00:00Z"))
        assert not emitted

    @pytest.mark.asyncio
    async def test_no_flag_when_no_activity_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        await dq.handle(_mk_event("contact_updated", {"accountId": "UK-0101"}))
        assert not emitted


class TestOpportunityIntegrity:
    @pytest.mark.asyncio
    async def test_flags_closed_won_without_close_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        ws = WorldState()
        monkeypatch.setattr("hub.agents._submit.state", ws)

        await dq.handle(_mk_event("opportunity_created", {
            "accountId": "UK-0103", "oppId": "OPP-BAD",
            "value": 0, "stage": "closed_won", "closeDate": None,
        }))
        # emit() merges extra fields to the top level of the entry dict
        issues_found = [e.get("issue") for e in emitted]
        assert "closed_won_without_close_date" in issues_found
        assert "zero_value_open_opportunity" in issues_found

    @pytest.mark.asyncio
    async def test_no_flag_for_valid_opportunity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))

        await dq.handle(_mk_event("opportunity_created", {
            "accountId": "UK-0103", "oppId": "OPP-GOOD",
            "value": 1_500_000, "stage": "proposal", "closeDate": None,
        }))
        assert not emitted

    @pytest.mark.asyncio
    async def test_zero_value_closed_lost_not_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zero value on closed_lost is expected — should not be flagged."""
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))

        await dq.handle(_mk_event("opportunity_created", {
            "accountId": "UK-0103", "oppId": "OPP-LOST",
            "value": 0, "stage": "closed_lost",
        }))
        assert not emitted


class TestOrphanedRep:
    @pytest.mark.asyncio
    async def test_tracks_departed_rep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        departed: set[str] = set()
        monkeypatch.setattr("hub.agents.data_quality._departed_reps", departed)

        await dq.handle(_mk_event("owner_changed", {
            "accountId": "NL-0848", "oldRepId": "R-22",
            "newRepId": "R-55", "reason": "rep_departure",
        }))
        assert "R-22" in departed

    @pytest.mark.asyncio
    async def test_flags_orphaned_opportunity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        departed: set[str] = {"R-22"}
        monkeypatch.setattr("hub.agents.data_quality._departed_reps", departed)

        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))
        ws = WorldState()
        monkeypatch.setattr("hub.agents._submit.state", ws)
        monkeypatch.setattr("hub.agents.data_quality.state", ws)

        await dq.handle(_mk_event("opportunity_stalled", {
            "accountId": "NL-0848", "oppId": "OPP-DQ-002",
            "value": 450_000, "repId": "R-22", "daysInStage": 47,
        }))
        actions = [e["action"] for e in emitted]
        assert "orphaned_opportunity_detected" in actions

    @pytest.mark.asyncio
    async def test_no_flag_for_active_rep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hub.agents.data_quality._departed_reps", set())
        emitted: list[dict] = []
        monkeypatch.setattr("hub.agents._submit.write", lambda e: emitted.append(e))

        await dq.handle(_mk_event("opportunity_stalled", {
            "accountId": "NL-0848", "oppId": "OPP-FINE",
            "value": 450_000, "repId": "R-55", "daysInStage": 10,
        }))
        assert not emitted

    @pytest.mark.asyncio
    async def test_owner_changed_without_rep_departure_not_tracked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        departed: set[str] = set()
        monkeypatch.setattr("hub.agents.data_quality._departed_reps", departed)

        await dq.handle(_mk_event("owner_changed", {
            "accountId": "NL-0847", "oldRepId": "R-22",
            "newRepId": "R-23", "reason": "territory_rebalance",
        }))
        assert not departed  # should NOT be marked as departed
