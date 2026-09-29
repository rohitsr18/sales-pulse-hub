"""Blast-radius scoring and autonomy gating. Four inputs (value, reach, reversible, external) produce a blast class (low/medium/high) and autonomy level. Note: blast radius != deal size."""

from __future__ import annotations
from typing import Any, Literal

BlastClass  = Literal["low", "medium", "high"]
Autonomy    = Literal["act", "recommend", "escalate"]
DeployStage = Literal["act_autonomous", "recommend", "act_with_approval"]

def compute(
    *,
    value: float,
    reach: int = 1,
    reversible: bool = True,
    external: bool = False,
) -> dict[str, Any]:
    """Compute blast radius and return a dict ready for the submission entry."""
    cls = _classify(value=value, reach=reach, reversible=reversible, external=external)
    autonomy, stage = _gate(cls)
    return {
        "class":            cls,
        "value":            value,
        "reach":            reach,
        "reversible":       reversible,
        "external":         external,
        "_autonomy":        autonomy,
        "_deploymentStage": stage,
    }

def _classify(*, value: float, reach: int, reversible: bool, external: bool) -> BlastClass:
    if external and not reversible:
        return "high"
    if reach > 10:
        return "high"
    if value > 2_000_000 and external:
        return "high"
    if external or not reversible or value > 200_000 or reach > 3:
        return "medium"
    return "low"

def _gate(cls: BlastClass) -> tuple[Autonomy, DeployStage]:
    return {
        "low":    ("act",       "act_autonomous"),
        "medium": ("recommend", "recommend"),
        "high":   ("escalate",  "act_with_approval"),
    }[cls]

def cohort_from_account_id(account_id: str) -> str:
    """Return the two-letter market code from an account ID like 'NL-0847'."""
    return account_id.split("-")[0].upper() if "-" in account_id else account_id[:2].upper()
