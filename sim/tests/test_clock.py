"""Unit tests for SimClock."""

import time

import pytest

from sim.clock import SIM_END, SIM_START, SimClock


class TestSimClockConstruction:
    def test_default_speed_and_instant(self) -> None:
        c = SimClock()
        assert c.speed == 60.0
        assert c.instant is False

    def test_custom_speed(self) -> None:
        assert SimClock(speed=300).speed == 300.0

    def test_invalid_speed_raises(self) -> None:
        with pytest.raises(ValueError):
            SimClock(speed=0)
        with pytest.raises(ValueError):
            SimClock(speed=-1)
        with pytest.raises(ValueError):
            SimClock(speed=1001)

    def test_instant_flag(self) -> None:
        assert SimClock(instant=True).instant is True


class TestSimClockNow:
    def test_returns_datetime_after_sim_start(self) -> None:
        c = SimClock(speed=60)
        assert c.now() >= SIM_START

    def test_never_exceeds_sim_end(self) -> None:
        c = SimClock(speed=60)
        # Wind wall base far into the past to force clock to ceiling
        c._wall_base_ms -= 10**9
        assert c.now() <= SIM_END

    def test_instant_returns_sim_end(self) -> None:
        assert SimClock(instant=True).now() == SIM_END

    def test_advances_over_real_time(self) -> None:
        speed = 1_000  # max allowed: 1 real ms ≈ 1 sim second
        c = SimClock(speed=speed)
        t0 = c.now()
        time.sleep(0.2)  # 200 ms real → ~200 sim seconds
        t1 = c.now()
        assert (t1 - t0).total_seconds() > 50  # at least 50 sim seconds advanced


class TestSimClockHelpers:
    def test_now_iso_is_valid(self) -> None:
        from datetime import datetime
        iso = SimClock(instant=True).now_iso()
        assert datetime.fromisoformat(iso)

    def test_seconds_until_zero_in_instant(self) -> None:
        assert SimClock(instant=True).seconds_until("2026-02-14T09:00:00Z") == 0.0

    def test_seconds_until_zero_for_past(self) -> None:
        c = SimClock(speed=60)
        assert c.seconds_until(SIM_START.isoformat()) == 0.0

    def test_seconds_until_positive_for_future(self) -> None:
        c = SimClock(speed=1)  # 1× — future stays far away
        future = SIM_END.isoformat()
        assert c.seconds_until(future) > 0

    def test_is_past_true_for_sim_start(self) -> None:
        assert SimClock(speed=60).is_past(SIM_START.isoformat())

    def test_is_past_false_for_sim_end_at_1x(self) -> None:
        assert not SimClock(speed=1).is_past(SIM_END.isoformat())
class TestSimClockReset:
    def test_reset_returns_near_sim_start(self) -> None:
        c = SimClock(speed=300)
        c._wall_base_ms -= 5_000  # simulate 5 real seconds having passed
        c.reset()
        delta = (c.now() - SIM_START).total_seconds()
        assert 0.0 <= delta < 1.0  # within 1 real second of start
