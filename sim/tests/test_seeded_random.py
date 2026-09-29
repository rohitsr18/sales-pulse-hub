"""Unit tests for SeededRandom / mulberry32."""

import pytest

from sim.seeded_random import SeededRandom, mulberry32


class TestMulberry32:
    def test_returns_callable(self) -> None:
        assert callable(mulberry32(42))

    def test_values_in_unit_interval(self) -> None:
        rand = mulberry32(42)
        for _ in range(1_000):
            v = rand()
            assert 0.0 <= v < 1.0

    def test_deterministic_same_seed(self) -> None:
        a, b = mulberry32(42), mulberry32(42)
        for _ in range(50):
            assert a() == b()

    def test_different_seeds_diverge(self) -> None:
        a_vals = [mulberry32(42)() for _ in range(20)]
        b_vals = [mulberry32(99)() for _ in range(20)]
        assert a_vals != b_vals

    def test_seed_zero(self) -> None:
        rand = mulberry32(0)
        assert 0.0 <= rand() < 1.0

    def test_seed_max(self) -> None:
        rand = mulberry32(0xFFFFFFFF)
        assert 0.0 <= rand() < 1.0


class TestSeededRandom:
    def test_invalid_seed_raises(self) -> None:
        with pytest.raises(ValueError):
            SeededRandom(-1)
        with pytest.raises(ValueError):
            SeededRandom(2**32)

    def test_float_range(self) -> None:
        r = SeededRandom(42)
        for _ in range(200):
            v = r.float()
            assert 0.0 <= v < 1.0

    def test_float_deterministic(self) -> None:
        assert SeededRandom(7).float() == SeededRandom(7).float()

    def test_int_within_bounds(self) -> None:
        r = SeededRandom(42)
        for _ in range(500):
            v = r.int(1, 10)
            assert 1 <= v <= 10

    def test_int_full_range(self) -> None:
        r = SeededRandom(1)
        seen = {r.int(1, 5) for _ in range(2_000)}
        assert seen == {1, 2, 3, 4, 5}

    def test_int_lo_equals_hi(self) -> None:
        assert SeededRandom(42).int(7, 7) == 7

    def test_pick_returns_element(self) -> None:
        arr = ["a", "b", "c", "d"]
        r = SeededRandom(42)
        for _ in range(200):
            assert r.pick(arr) in arr

    def test_pick_deterministic(self) -> None:
        arr = [10, 20, 30]
        assert SeededRandom(5).pick(arr) == SeededRandom(5).pick(arr)

    def test_bool_always_true_at_p1(self) -> None:
        r = SeededRandom(42)
        assert all(r.bool(1.0) for _ in range(50))

    def test_bool_always_false_at_p0(self) -> None:
        r = SeededRandom(42)
        assert not any(r.bool(0.0) for _ in range(50))

    def test_id_format(self) -> None:
        r = SeededRandom(42)
        result = r.id("evt_")
        assert result.startswith("evt_")
        suffix = result[4:]
        assert suffix.isdigit()
        assert 1000 <= int(suffix) <= 9999

    def test_default_seed_equals_42(self) -> None:
        assert SeededRandom().float() == SeededRandom(42).float()
