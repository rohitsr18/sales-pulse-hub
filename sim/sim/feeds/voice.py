"""voice.py — Field Notes / Voice feed (port 7002)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from sim.feed_base import build_feed_app

# Safe filename pattern — prevents path traversal attacks
_SAFE_MEMO_ID = re.compile(r"^[\w.\-]{1,64}$")

def build_voice_feed(clock: Any) -> tuple[Any, Any]:
    app, _broadcast = build_feed_app(
        source="voice",
        feed_name="Field Notes / Voice Feed",
        clock=clock,
        capabilities=["voice_memo_received"],
        build_snapshot=lambda _at: {"memos": []},
    )

    # In-memory store: memoId → {transcript, durationSec}
    _memo_store: dict[str, dict[str, Any]] = {}

    @app.get("/audio/{memo_id}")
    async def get_audio(memo_id: str, request: Request) -> JSONResponse:  # noqa: ARG001
        if not _SAFE_MEMO_ID.match(memo_id):
            return JSONResponse({"error": "Invalid memo ID"}, status_code=400)
        memo = _memo_store.get(memo_id)
        if memo is None:
            return JSONResponse({"error": "Memo not found"}, status_code=404)
        return JSONResponse({"memoId": memo_id, **memo})

    # Wrap broadcast so memos are cached as they are published
    async def broadcast(event: dict[str, Any]) -> None:
        if event.get("type") == "voice_memo_received":
            payload = event.get("payload", {})
            audio_url: str = payload.get("audioUrl", "")
            memo_id = audio_url.split("/")[-1] if audio_url else ""
            if memo_id:
                _memo_store[memo_id] = {
                    "transcript":  payload.get("transcript", ""),
                    "durationSec": payload.get("durationSec", 0),
                }
        await _broadcast(event)

    return app, broadcast
