from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from pjm_nowcast.api.discovery import (
    llms_txt,
    load_demo_sample,
    robots_txt,
    service_card,
    skill_markdown,
    well_known_x402,
)
from pjm_nowcast.api.errors import error_response
from pjm_nowcast.settings import Settings

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_ICON_TYPES = {
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


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
        "facilitators": settings.facilitator_status(),
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


@router.get("/favicon.ico", include_in_schema=False)
@router.get("/favicon.png", include_in_schema=False)
@router.get("/favicon.svg", include_in_schema=False)
def favicon(request: Request):
    suffix = Path(request.url.path).suffix.lower()
    path = STATIC_DIR / f"favicon{suffix}"
    media = _ICON_TYPES.get(suffix, "application/octet-stream")
    if not path.is_file():
        return error_response(404, "not_found", "Favicon is not packaged.")
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/swagger.json", summary="OpenAPI alias", tags=["free"])
def swagger(request: Request):
    return JSONResponse(request.app.openapi())


@router.get("/skill.md", include_in_schema=False)
@router.get("/SKILL.md", include_in_schema=False)
def skill(request: Request):
    settings: Settings = request.app.state.settings
    return PlainTextResponse(skill_markdown(settings), media_type="text/markdown")


@router.get("/llms.txt", summary="LLM discovery index", tags=["free"])
def llms(request: Request):
    return PlainTextResponse(llms_txt(request.app.state.settings), media_type="text/plain")


@router.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse(robots_txt(), media_type="text/plain")


@router.get("/.well-known/x402", summary="x402 well-known", tags=["free"])
@router.get("/.well-known/x402.json", include_in_schema=False)
def well_known(request: Request):
    return JSONResponse(well_known_x402(request.app.state.settings))


@router.get("/v1/demo/sample", summary="Fixed demo sample", tags=["free"])
def demo_sample(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.free_demo_enabled:
        return error_response(404, "not_found", "Demo sample is disabled.")
    return JSONResponse(load_demo_sample())
