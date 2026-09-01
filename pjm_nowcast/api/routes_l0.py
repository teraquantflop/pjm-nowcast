from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from pjm_nowcast.api.discovery import (
    agent_card,
    health_payload,
    llms_txt,
    load_demo_sample,
    robots_txt,
    service_card,
    skill_markdown,
    well_known_x402,
    x402_resources,
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
    return health_payload(request.app.state.settings, request.app.state.store)


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
@router.get("/llm.txt", include_in_schema=False)
@router.get("/.well-known/llms.txt", include_in_schema=False)
@router.get("/.well-known/llm.txt", include_in_schema=False)
def llms(request: Request):
    return PlainTextResponse(llms_txt(request.app.state.settings), media_type="text/plain")


@router.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse(
        robots_txt(),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/.well-known/x402", summary="x402 well-known", tags=["free"])
@router.get("/.well-known/x402.json", include_in_schema=False)
def well_known(request: Request):
    return JSONResponse(well_known_x402(request.app.state.settings))


@router.get("/.well-known/agent.json", summary="Agent card", tags=["free"])
def well_known_agent(request: Request):
    return JSONResponse(agent_card(request.app.state.settings))


@router.get("/.well-known/x402-resources", summary="x402 paid resources", tags=["free"])
def well_known_resources(request: Request):
    return JSONResponse(x402_resources(request.app.state.settings))


@router.get(
    "/v1/demo/sample",
    summary="Fetch a synthetic unpaid nowcast sample fixture",
    tags=["free"],
)
def demo_sample():
    return JSONResponse(load_demo_sample())


_DEMO_POST_MESSAGE = (
    "Do not POST /v1/demo/sample. Use GET for the synthetic unpaid fixture. "
    "Paid nowcast routes are POST /v1/nowcast/latest, /v1/nowcast/history, "
    "and /v1/nowcast/history/extended."
)


@router.post("/v1/demo/sample", include_in_schema=False)
@router.put("/v1/demo/sample", include_in_schema=False)
@router.patch("/v1/demo/sample", include_in_schema=False)
@router.delete("/v1/demo/sample", include_in_schema=False)
def demo_sample_method_not_allowed():
    return JSONResponse(
        status_code=405,
        content={
            "error": "method_not_allowed",
            "message": _DEMO_POST_MESSAGE,
            "path": "/v1/demo/sample",
            "allow": ["GET"],
        },
        headers={"Allow": "GET"},
    )
