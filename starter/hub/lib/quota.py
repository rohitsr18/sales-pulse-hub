"""Shared token budget across all LLM agents."""

from __future__ import annotations

import os

from hub.lib import logger

_MAX: int = int(os.environ.get("LLM_QUOTA_TOKENS", "500000"))
_used: int = 0

def consume(tokens: int) -> None:
    global _used
    _used += tokens
    if _used > _MAX:
        logger.warn("Token quota exhausted", used=_used, max=_MAX)

def remaining() -> int:
    return max(0, _MAX - _used)

def has_quota(estimated: int = 1_000) -> bool:
    return remaining() >= estimated

def summary() -> dict[str, int]:
    return {"used": _used, "max": _MAX, "remaining": remaining()}

def reset() -> None:
    """Reset for tests only."""
    global _used
    _used = 0
