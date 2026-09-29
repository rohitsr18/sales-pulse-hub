"""Builds a spec-compliant submission entry and writes it to submission.jsonl."""

from __future__ import annotations

from typing import Any

from hub.tools import blast_radius as br
from hub.tools.submission_writer import write
from hub.store.world_state import state

def emit(
    *,
    sim_time: str,
    agent: str,
    action: str,
    account_id: str,
    value: float,
    currency: str = "EUR",
    opportunity_id: str | None = None,
    reach: int = 1,
    reversible: bool = True,
    external: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Build a spec-compliant submission entry and write it to submission.jsonl.
    Also logs the action to WorldState for dashboard display.
    """
    blast = br.compute(
        value=value,
        reach=reach,
        reversible=reversible,
        external=external,
    )
    cohort = br.cohort_from_account_id(account_id)

    target: dict[str, Any] = {
        "accountId": account_id,
        "value":     value,
        "currency":  currency,
    }
    if opportunity_id:
        target["opportunityId"] = opportunity_id

    entry: dict[str, Any] = {
        "simTime":         sim_time,
        "agent":           agent,
        "action":          action,
        "target":          target,
        "blastRadius": {
            "class":      blast["class"],
            "value":      blast["value"],
            "reach":      blast["reach"],
            "reversible": blast["reversible"],
            "external":   blast["external"],
        },
        "autonomy":        blast["_autonomy"],
        "deploymentStage": blast["_deploymentStage"],
        "cohort":          cohort,
    }
    if extra:
        entry.update(extra)

    # Write ONLY spec-defined fields to submission.jsonl (grader is strict)
    spec_entry: dict[str, Any] = {
        "simTime":         entry["simTime"],
        "agent":           entry["agent"],
        "action":          entry["action"],
        "target":          entry["target"],
        "blastRadius":     entry["blastRadius"],
        "autonomy":        entry["autonomy"],
        "deploymentStage": entry["deploymentStage"],
        "cohort":          entry["cohort"],
    }
    write(spec_entry)

    # Mirror full entry (with extra context) to dashboard action log
    state.log_action(entry)
    state.update_agent_activity(agent, action, cohort)
