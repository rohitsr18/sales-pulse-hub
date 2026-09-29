"""Unit tests for sim.validator."""

import pytest

from sim.validator import ValidationError, parse_seed, parse_sim_time, parse_speed


class TestParseSeed:
    def test_none_returns_42(self) -> None:
        assert parse_seed(None) == 42

    def test_valid_seed(self) -> None:
        assert parse_seed("99") == 99

    def test_seed_zero(self) -> None:
        assert parse_seed("0") == 0

    def test_seed_max(self) -> None:
        assert parse_seed(str(2**32 - 1)) == 2**32 - 1

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_seed("-1")

    def test_non_integer_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_seed("3.14")

    def test_overflow_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_seed(str(2**32))

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_seed("abc")


class TestParseSpeed:
    def test_none_returns_60(self) -> None:
        assert parse_speed(None) == 60.0

    def test_valid_speed(self) -> None:
        assert parse_speed("300") == 300.0

    def test_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_speed("0")

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_speed("-10")

    def test_over_max_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_speed("1001")

    def test_fractional_speed(self) -> None:
        assert parse_speed("0.5") == 0.5


class TestParseSimTime:
    def test_none_returns_none(self) -> None:
        assert parse_sim_time(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_sim_time("") is None

    def test_valid_iso(self) -> None:
        result = parse_sim_time("2026-02-14T09:12:00Z")
        assert result is not None
        assert "2026-02-14" in result

    def test_invalid_date_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_sim_time("not-a-date")

    def test_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            parse_sim_time("2026-02-14T09:12:00.000Z_extra_garbage_that_is_very_long")
