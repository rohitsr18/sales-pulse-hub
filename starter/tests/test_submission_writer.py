"""Unit tests for submission_writer — new spec schema (agent/target/blastRadius)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _tmp_submission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect submission output to a temp file; force module reload."""
    monkeypatch.setenv("SUBMISSION_PATH", str(tmp_path / "sub.jsonl"))
    import importlib
    import hub.tools.submission_writer as sw
    importlib.reload(sw)


def _read_lines(tmp_path: Path) -> list[dict]:  # type: ignore[type-arg]
    p = tmp_path / "sub.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def _valid() -> dict:  # type: ignore[type-arg]
    return {
        "simTime":         "2026-02-14T09:12:00Z",
        "agent":           "fastflow",
        "action":          "capital_quote_configured",
        "target":          {"accountId": "NL-0847", "value": 6_771_000, "currency": "EUR"},
        "blastRadius":     {"class": "high", "value": 6_771_000, "reach": 1, "reversible": False, "external": True},
        "autonomy":        "escalate",
        "deploymentStage": "act_with_approval",
        "cohort":          "NL",
    }


class TestWrite:
    def test_writes_valid_entry(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        sw.write(_valid())
        lines = _read_lines(tmp_path)
        assert len(lines) == 1
        r = lines[0]
        assert r["agent"] == "fastflow"
        assert r["blastRadius"]["class"] == "high"
        assert r["autonomy"] == "escalate"
        assert r["deploymentStage"] == "act_with_approval"
        assert "_writtenAt" in r

    def test_skips_missing_top_field(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); del e["agent"]
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_skips_missing_target_field(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); e["target"] = {"accountId": "NL-0847"}  # no value/currency
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_skips_missing_blast_field(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); del e["blastRadius"]["reach"]
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_skips_invalid_blast_class(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); e["blastRadius"]["class"] = "CRITICAL"
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_skips_invalid_autonomy(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); e["autonomy"] = "supervised"  # old schema — not valid
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_skips_invalid_deployment_stage(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        e = _valid(); e["deploymentStage"] = "auto"  # old schema
        sw.write(e)
        assert _read_lines(tmp_path) == []

    def test_multiple_writes(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        sw.write(_valid()); sw.write({**_valid(), "action": "a2"})
        assert len(_read_lines(tmp_path)) == 2

    def test_all_blast_classes_accepted(self, tmp_path: Path) -> None:
        import hub.tools.submission_writer as sw
        combos = [
            ("low",    "act",       "act_autonomous"),
            ("medium", "recommend", "recommend"),
            ("high",   "escalate",  "act_with_approval"),
        ]
        for cls, auto, stage in combos:
            e = _valid()
            e["blastRadius"]["class"] = cls
            e["autonomy"]        = auto
            e["deploymentStage"] = stage
            sw.write(e)
        assert len(_read_lines(tmp_path)) == 3
