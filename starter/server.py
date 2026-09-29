"""Hub entry point — starts the FastAPI server and agent orchestrator in one asyncio loop."""

from __future__ import annotations

import asyncio
import os
import signal

import uvicorn
from dotenv import load_dotenv

load_dotenv()  # load .env before anything else reads env vars

from hub.lib import logger  # noqa: E402 (import after load_dotenv intentional)
from hub.agents.orchestrator import start as start_orchestrator
from hub.main import app


async def main() -> None:
    port = int(os.environ.get("PORT", "3000"))
    logger.info("SalesPulse Hub starting", port=port)

    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    )

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: setattr(server, "should_exit", True))

    await asyncio.gather(
        server.serve(),
        start_orchestrator(),
        return_exceptions=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
