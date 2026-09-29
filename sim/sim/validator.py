"""Query-parameter validation for sim API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

_MAX_SEED = 2**32 - 1
_MAX_SPEED = 1_000.0

class ValidationError(ValueError):
    """Raised for invalid API inputs; serialised to HTTP 400 by error handlers."""

def parse_seed(raw: str | None) -> int:
    """Parse and validate the ?seed= query parameter. Defaults to 42."""
    if raw is None:
        return 42
    try:
        n = int(raw)
    except ValueError:
        raise ValidationError(f"seed must be an integer, got '{raw}'") from None
    if n < 0 or n > _MAX_SEED:
        raise ValidationError(f"seed must be in [0, {_MAX_SEED}], got {n}")
    return n

def parse_speed(raw: str | None) -> float:
    """Parse and validate the ?speed= query parameter. Defaults to 60."""
    if raw is None:
        return 60.0
    try:
        n = float(raw)
    except ValueError:
        raise ValidationError(f"speed must be a number, got '{raw}'") from None
    if n <= 0 or n > _MAX_SPEED:
        raise ValidationError(f"speed must be in (0, {_MAX_SPEED}], got {n}")
    return n

def parse_sim_time(raw: str | None) -> str | None:
    """Validate an ISO-8601 simTime string. Returns None if missing."""
    if not raw:
        return None
    if len(raw) > 32:
        raise ValidationError("'at' must be a valid ISO-8601 datetime string (max 32 chars)")
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        raise ValidationError(f"'{raw}' is not a valid ISO-8601 datetime") from None
