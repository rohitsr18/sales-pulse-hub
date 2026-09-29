"""Mulberry32 seedable PRNG — same seed always produces the same sequence."""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

def mulberry32(seed: int) -> Callable[[], float]:
    """Return a closure that yields the next pseudo-random float in [0, 1)."""
    a: list[int] = [seed & 0xFFFFFFFF]

    def _rand() -> float:
        a[0] = (a[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a[0] ^ (a[0] >> 15)) * (1 | a[0])) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t))) & 0xFFFFFFFF
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return t / 4_294_967_296.0

    return _rand

class SeededRandom:
    """Convenience wrapper around Mulberry32 with typed helper methods."""

    def __init__(self, seed: int = 42) -> None:
        if not (0 <= seed <= 0xFFFFFFFF):
            raise ValueError(f"seed must be an integer in [0, 2^32-1], got {seed}")
        self._rand = mulberry32(seed)

    def float(self) -> float:
        """Return a float in [0, 1)."""
        return self._rand()

    def int(self, lo: int, hi: int) -> int:
        """Return an integer in [lo, hi] inclusive."""
        return int(self._rand() * (hi - lo + 1)) + lo

    def pick(self, seq: list[T]) -> T:
        """Return a uniformly random element from seq."""
        return seq[int(self._rand() * len(seq))]

    def bool(self, p: float = 0.5) -> bool:
        """Return True with probability p."""
        return self._rand() < p

    def id(self, prefix: str) -> str:
        """Return prefix + 4-digit number."""
        return f"{prefix}{int(self._rand() * 9000) + 1000}"
