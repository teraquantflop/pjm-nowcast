from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pjm_nowcast.api.discovery import load_demo_sample, service_card
from pjm_nowcast.api.errors import error_response
from pjm_nowcast.settings import Settings

router = APIRouter()


@router.get("/health", summary="Health", tags=["free"])
def health(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    store = request.app.state.store
    last = store.latest()
    poll = store.last_poll()
    now = datetime.now(timezone.utc)
    data = None
    status = "ok"
    if last is None:
        status = "unavailable"
    else:
        age = max(0, int((now - last.fetched_at).total_seconds()))
        stale = age > settings.stale_after_seconds
        data = {
            "asOf": last.ts.isoformat(),
            "polledAt": last.fetched_at.isoformat(),
            "ageSeconds": age,
            "maxAgeSeconds": settings.stale_after_seconds,
            "stale": stale,
            "observationCount": store.count(),
        }
        last_run = poll.get("lastRun")
        last_failed = last_run is not None and int(last_run["ok"]) == 0
        if stale or last_failed:
            status = "degraded"
    return {
        "status": status,
        "db": "ok",
        "poller": {
            "lastSuccessAt": poll.get("lastSuccessAt"),
            "lastError": poll.get("lastError"),
            "lastOk": (
                None
                if poll.get("lastRun") is None
                else bool(int(poll["lastRun"]["ok"]))
            ),
        },
        "data": data,
    }


@router.get("/", summary="Service card", tags=["free"])
def root(request: Request) -> dict:
    return service_card(request.app.state.settings)


@router.get("/v1/discovery", summary="Service card (alias)", tags=["free"])
def discovery(request: Request) -> dict:
    return service_card(request.app.state.settings)


@router.get("/v1/demo/sample", summary="Fixed demo sample", tags=["free"])
def demo_sample(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.free_demo_enabled:
        return error_response(404, "not_found", "Demo sample is disabled.")
    return JSONResponse(load_demo_sample())
