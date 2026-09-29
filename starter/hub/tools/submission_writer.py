"""Append-only writer for submission.jsonl. Validates the spec schema before every write."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hub.lib import logger

_PATH = Path(os.environ.get("SUBMISSION_PATH", "submission.jsonl"))

_REQUIRED_TOP: frozenset[str] = frozenset({
    "simTime", "agent", "action", "target", "blastRadius",
    "autonomy", "deploymentStage", "cohort",
})
_REQUIRED_TARGET: frozenset[str] = frozenset({"accountId", "value", "currency"})
_REQUIRED_BLAST:  frozenset[str] = frozenset({"class", "value", "reach", "reversible", "external"})
_VALID_BLAST     = frozenset({"low", "medium", "high"})
_VALID_AUTONOMY  = frozenset({"act", "recommend", "escalate"})
_VALID_STAGE     = frozenset({"act_autonomous", "recommend", "act_with_approval"})

try:
    _fh = _PATH.open("a", encoding="utf-8", buffering=1)
except OSError as _e:
    logger.error("Cannot open submission.jsonl", path=str(_PATH), err=str(_e))
    _fh = None  # type: ignore[assignment]

def write(entry: dict[str, Any]) -> None:
    """Validate and append one action entry to submission.jsonl."""
    if _fh is None:
        return

    # Top-level required fields
    missing_top = _REQUIRED_TOP - entry.keys()
    if missing_top:
        logger.warn("Submission entry missing top-level fields — skipped", missing=sorted(missing_top))
        return

    # target sub-object
    target = entry.get("target") or {}
    missing_target = _REQUIRED_TARGET - target.keys()
    if missing_target:
        logger.warn("Submission target missing fields — skipped", missing=sorted(missing_target))
        return

    # blastRadius sub-object
    blast = entry.get("blastRadius") or {}
    missing_blast = _REQUIRED_BLAST - blast.keys()
    if missing_blast:
        logger.warn("Submission blastRadius missing fields — skipped", missing=sorted(missing_blast))
        return

    if blast.get("class") not in _VALID_BLAST:
        logger.warn("Invalid blastRadius.class", value=blast.get("class"))
        return
    if entry["autonomy"] not in _VALID_AUTONOMY:
        logger.warn("Invalid autonomy", value=entry["autonomy"])
        return
    if entry["deploymentStage"] not in _VALID_STAGE:
        logger.warn("Invalid deploymentStage", value=entry["deploymentStage"])
        return

    # Write ONLY the 8 spec-defined fields — grader rejects any extra keys
    record: dict[str, Any] = {
        "simTime":         entry["simTime"],
        "agent":           entry["agent"],
        "action":          entry["action"],
        "target":          entry["target"],
        "blastRadius":     entry["blastRadius"],
        "autonomy":        entry["autonomy"],
        "deploymentStage": entry["deploymentStage"],
        "cohort":          entry["cohort"],
    }

    try:
        _fh.write(json.dumps(record) + "\n")
        _fh.flush()
        logger.info(
            "Action written",
            agent=entry.get("agent"),
            action=entry.get("action"),
            accountId=target.get("accountId"),
            blastClass=blast.get("class"),
            autonomy=entry.get("autonomy"),
            value=target.get("value"),
        )
    except OSError as exc:
        logger.error("Write failed", err=str(exc))

def close() -> None:
    if _fh is not None:
        _fh.close()
