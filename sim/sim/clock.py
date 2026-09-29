"""SimClock — maps real wall-clock elapsed time into simulated time."""

from __future__ import annotations

import time
from datetime import datetime, timezone

SIM_START = datetime(2026, 2,  1,  8, 0, 0, tzinfo=timezone.utc)
SIM_END   = datetime(2026, 6,  1, 23, 59, 59, tzinfo=timezone.utc)  # 120 sim-days

_SIM_START_MS = SIM_START.timestamp() * 1_000
_SIM_END_MS = SIM_END.timestamp() * 1_000

class SimClock:
    def __init__(self, speed: float = 60.0, instant: bool = False) -> None:
        if speed <= 0 or speed > 1_000:
            raise ValueError(f"speed must be in (0, 1000], got {speed}")
        self.speed = speed
        self.instant = instant
        self._sim_base_ms: float = _SIM_START_MS
        self._wall_base_ms: float = time.monotonic() * 1_000

    def now(self) -> datetime:
        """Current sim time as an aware UTC datetime."""
        if self.instant:
            return SIM_END
        wall_elapsed = time.monotonic() * 1_000 - self._wall_base_ms
        sim_ms = min(self._sim_base_ms + wall_elapsed * self.speed, _SIM_END_MS)
        return datetime.fromtimestamp(sim_ms / 1_000, tz=timezone.utc)

    def now_iso(self) -> str:
        return self.now().isoformat()

    def seconds_until(self, sim_time_iso: str) -> float:
        """Real seconds to wait until a given sim time fires. 0 in instant mode."""
        if self.instant:
            return 0.0
        target_ms = _parse_ms(sim_time_iso)
        delta_sim_ms = target_ms - self.now().timestamp() * 1_000
        return max(0.0, delta_sim_ms / self.speed / 1_000)

    def is_past(self, sim_time_iso: str) -> bool:
        return _parse_ms(sim_time_iso) <= self.now().timestamp() * 1_000

    def reset(self) -> None:
        self._sim_base_ms = _SIM_START_MS
        self._wall_base_ms = time.monotonic() * 1_000

def _parse_ms(iso: str) -> float:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1_000
