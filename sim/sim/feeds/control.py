"""control.py — Control Plane (port 7000)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sim import logger
from sim.validator import ValidationError, parse_seed

_FEED_DIR = [
    {"source": "crm",    "port": 7001, "name": "CRM Feed"},
    {"source": "voice",  "port": 7002, "name": "Field Notes / Voice"},
    {"source": "quotes", "port": 7003, "name": "Quote Inbox"},
    {"source": "market", "port": 7004, "name": "Market Signals"},
    {"source": "supply", "port": 7005, "name": "Supply / Factory"},
]

def build_control_app(
    clock: Any,
    config: dict[str, Any],
    on_reset: Callable[[int], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="SalesPulse Control Plane", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "simTime": clock.now_iso()}

    @app.get("/clock")
    async def get_clock() -> dict[str, Any]:
        return {"simTime": clock.now_iso(), "speed": clock.speed, "instant": clock.instant}

    @app.get("/config")
    async def get_config() -> dict[str, Any]:
        return {"seed": config.get("seed", 42), "speed": clock.speed, "instant": clock.instant}

    @app.get("/meta")
    async def meta() -> dict[str, Any]:
        return {"feeds": _FEED_DIR, "simStart": "2026-02-10T08:00:00Z", "simEnd": "2026-02-24T23:59:59Z"}

    @app.post("/reset")
    async def reset(seed: str | None = None) -> JSONResponse:
        try:
            new_seed = parse_seed(seed)
        except ValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        logger.info("Simulation reset", seed=new_seed)
        config["seed"] = new_seed
        clock.reset()
        if on_reset:
            on_reset(new_seed)
        return JSONResponse({"ok": True, "seed": new_seed, "simTime": clock.now_iso()})

    @app.exception_handler(Exception)
    async def _err(_req: Request, exc: Exception) -> JSONResponse:
        logger.error("Control plane error", err=str(exc))
        return JSONResponse({"error": "InternalError"}, status_code=500)

    return app
