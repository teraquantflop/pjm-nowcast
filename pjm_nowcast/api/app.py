"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pjm_nowcast import DISCLAIMER, __version__
from pjm_nowcast.api.openapi import install_openapi
from pjm_nowcast.api.routes_l0 import router as l0_router
from pjm_nowcast.api.routes_nowcast import router as nowcast_router
from pjm_nowcast.db.store import Store
from pjm_nowcast.payments.gate import PaymentGateMiddleware
from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    log.info(
        "storage data_dir=%s db=%s snapshot=%s",
        settings.data_dir,
        settings.database_path,
        settings.snapshot_path,
    )
    store = Store(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        poller_task = None
        if settings.run_poller:
            from pjm_nowcast.poller.job import run_poller

            poller_task = asyncio.create_task(run_poller(store, settings, stop))
            log.info("Background poller task started")
        app.state.stop = stop
        app.state.poller_task = poller_task
        try:
            yield
        finally:
            stop.set()
            if poller_task is not None:
                poller_task.cancel()
                try:
                    await poller_task
                except (asyncio.CancelledError, Exception):
                    pass
            store.close()

    app = FastAPI(
        title="pjm-nowcast",
        version=__version__,
        description=(
            "Trailing and semi-live descriptive statistics on PJM RTO LMP, "
            "zonal LMP spreads, and RTO load. " + DISCLAIMER
        ),
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"],
        )

    app.add_middleware(PaymentGateMiddleware, settings=settings, store=store)

    app.include_router(l0_router)
    app.include_router(nowcast_router)

    if settings.mcp_enabled:
        from pjm_nowcast.mcp_facade.server import mcp_router

        app.include_router(
            mcp_router(),
            prefix=settings.mcp_path,
            include_in_schema=False,
        )

    install_openapi(app, settings)
    return app
