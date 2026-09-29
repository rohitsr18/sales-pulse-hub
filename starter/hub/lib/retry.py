"""Async exponential-backoff retry for transient API errors."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from hub.lib import logger

T = TypeVar("T")

_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_ms: float = 500.0,
    max_delay_ms: float = 10_000.0,
    context: str = "",
) -> T:
    """Retry *fn* up to *max_attempts* times with full-jitter backoff."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            status: int | None = getattr(exc, "status_code", None) or getattr(exc, "status", None)
            is_retryable = status is None or status in _RETRYABLE_STATUSES

            if not is_retryable or attempt == max_attempts:
                raise

            # Full jitter: uniform in [0, min(cap, base * 2^attempt)]
            cap = min(max_delay_ms, base_ms * (2**attempt))
            delay_ms = random.uniform(0, cap)  # noqa: S311
            logger.warn(
                "Retrying after error",
                context=context,
                attempt=attempt,
                max_attempts=max_attempts,
                delay_ms=round(delay_ms),
                err=str(exc),
            )
            await asyncio.sleep(delay_ms / 1_000)

    raise last_exc  # type: ignore[misc]
