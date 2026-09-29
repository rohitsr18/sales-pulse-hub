"""FastAPI app factory used by every feed server. Returns (app, broadcast_fn)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from sim import logger
from sim.clock import SIM_START, SIM_END
from sim.validator import ValidationError, parse_sim_time

_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000"]
_HEARTBEAT_INTERVAL = 15.0  # seconds — keeps TCP connection alive through proxies

def build_feed_app(
    *,
    source: str,
    feed_name: str,
    clock: Any,
    capabilities: list[str],
    schema_version: str = "1.0",
    build_snapshot: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[FastAPI, Callable[..., Any]]:
    """
    Build a FastAPI application for one SSE feed.

    Returns:
        (app, broadcast)  — broadcast is ``async def broadcast(event: dict) -> None``
    """
    app = FastAPI(title=feed_name, docs_url=None, redoc_url=None)

    # Restrict CORS to localhost — this is not a public API
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Connected SSE client queues
    _clients: list[asyncio.Queue[dict[str, Any]]] = []
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "feed": source, "simTime": clock.now_iso()}
    @app.get("/meta")
    async def meta() -> dict[str, Any]:
        return {
            "feed": source,
            "feedName": feed_name,
            "schemaVersion": schema_version,
            "capabilities": capabilities,
            "simStart": SIM_START.isoformat(),
            "simEnd":   SIM_END.isoformat(),
        }
    @app.get("/snapshot")
    async def snapshot(at: str | None = None) -> JSONResponse:
        try:
            sim_time = parse_sim_time(at) or clock.now_iso()
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        data = build_snapshot(sim_time) if build_snapshot else {}
        return JSONResponse({"simTime": sim_time, "source": source, "data": data})
    @app.get("/stream")
    async def stream(request: Request) -> EventSourceResponse:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _clients.append(queue)
        logger.info("SSE client connected", feed=source, total=len(_clients))

        async def _generator() -> AsyncGenerator[dict[str, Any], None]:
            # Handshake
            yield {
                "event": "connected",
                "data": json.dumps({"simTime": clock.now_iso(), "feed": source}),
            }
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
                        yield {"event": event["type"], "data": json.dumps(event)}
                    except asyncio.TimeoutError:
                        yield {"comment": "heartbeat"}
            finally:
                if queue in _clients:
                    _clients.remove(queue)
                logger.info("SSE client disconnected", feed=source, total=len(_clients))

        return EventSourceResponse(_generator())
    @app.exception_handler(Exception)
    async def _generic_error(_req: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error", feed=source, err=str(exc))
        return JSONResponse({"error": "InternalError", "message": "An unexpected error occurred"}, status_code=500)
    async def broadcast(event: dict[str, Any]) -> None:
        for q in list(_clients):
            await q.put(event)

    return app, broadcast
