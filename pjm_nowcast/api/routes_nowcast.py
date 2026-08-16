from __future__ import annotations

from fastapi import APIRouter, Request

from pjm_nowcast.api.errors import data_unavailable, error_response
from pjm_nowcast.api.schemas import (
    ExtendedHistoryRequest,
    HistoryRequest,
    LatestRequest,
    parse_json_body,
)
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.assemble import assemble_history, assemble_latest

router = APIRouter()


@router.post("/v1/nowcast/latest")
async def latest(request: Request):
    settings: Settings = request.app.state.settings
    raw = await request.body()
    payload = parse_json_body(raw, LatestRequest)
    assert isinstance(payload, LatestRequest)
    body = assemble_latest(
        request.app.state.store,
        settings,
        families=payload.families,
    )
    if body is None:
        return data_unavailable()
    return body


@router.post("/v1/nowcast/history")
async def history(request: Request):
    settings: Settings = request.app.state.settings
    raw = await request.body()
    try:
        payload = parse_json_body(raw, HistoryRequest)
    except Exception as exc:
        return error_response(400, "invalid_request", str(exc))
    assert isinstance(payload, HistoryRequest)
    if payload.windowHours > settings.l2_max_hours:
        return error_response(
            400,
            "invalid_request",
            f"windowHours must be 1–{settings.l2_max_hours} on this route.",
        )
    body = assemble_history(
        request.app.state.store,
        settings,
        window_hours=payload.windowHours,
        families=payload.families,
        resolution="native",
        compare="none",
    )
    if body is None:
        return data_unavailable()
    return body


@router.post("/v1/nowcast/history/extended")
async def history_extended(request: Request):
    settings: Settings = request.app.state.settings
    raw = await request.body()
    try:
        payload = parse_json_body(raw, ExtendedHistoryRequest)
    except Exception as exc:
        return error_response(400, "invalid_request", str(exc))
    assert isinstance(payload, ExtendedHistoryRequest)
    if payload.windowHours > settings.l3_max_hours:
        return error_response(
            400,
            "invalid_request",
            f"windowHours must be 1–{settings.l3_max_hours} on this route.",
        )
    body = assemble_history(
        request.app.state.store,
        settings,
        window_hours=payload.windowHours,
        families=payload.families,
        resolution=payload.resolution,
        compare=payload.compare,
    )
    if body is None:
        return data_unavailable()
    return body
