"""Structured JSON logger. Writes one line per entry to stdout; redacts sensitive keys."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

_LEVELS: dict[str, int] = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_MIN_LEVEL = _LEVELS.get(os.environ.get("LOG_LEVEL", "info").lower(), 20)

_SENSITIVE = re.compile(r"key|secret|token|password|auth|credential", re.IGNORECASE)

def _redact(obj: Any, depth: int = 0) -> Any:  # noqa: ANN401
    if depth > 5 or not isinstance(obj, dict):
        return obj
    return {
        k: "[REDACTED]" if _SENSITIVE.search(k) else _redact(v, depth + 1)
        for k, v in obj.items()
    }

def _write(level: str, msg: str, **meta: Any) -> None:
    if _LEVELS.get(level, 0) < _MIN_LEVEL:
        return
    entry = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "level": level,
        "svc": "sim",
        "msg": msg,
        **_redact(meta),
    }
    sys.stdout.write(json.dumps(entry) + "\n")
    sys.stdout.flush()

def debug(msg: str, **meta: Any) -> None:
    _write("debug", msg, **meta)

def info(msg: str, **meta: Any) -> None:
    _write("info", msg, **meta)

def warn(msg: str, **meta: Any) -> None:
    _write("warn", msg, **meta)

def error(msg: str, **meta: Any) -> None:
    _write("error", msg, **meta)
