from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from pjm_nowcast.api.errors import data_unavailable, error_response
from pjm_nowcast.api.schemas import (
    AsofRequest,
    ExtendedHistoryRequest,
    HistoryRequest,
    LatestRequest,
    parse_json_body,
)
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.assemble import (
    assemble_asof,
    assemble_history,
    assemble_latest,
    assemble_regime,
    assemble_spreads,
)

router = APIRouter()


@router.post("/v1/nowcast/latest", summary="Latest snapshot", tags=["nowcast"])
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


@router.post("/v1/nowcast/history", summary="Short history", tags=["nowcast"])
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


@router.post(
    "/v1/nowcast/history/extended",
    summary="Extended history",
    tags=["nowcast"],
)
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


@router.post("/v1/nowcast/regime", summary="HMM regime snapshot", tags=["nowcast"])
async def regime(request: Request):
    settings: Settings = request.app.state.settings
    await request.body()
    body = assemble_regime(request.app.state.store, settings)
    if body is None:
        return data_unavailable()
    return body


@router.post("/v1/nowcast/spreads", summary="Zone spread table", tags=["nowcast"])
async def spreads(request: Request):
    settings: Settings = request.app.state.settings
    await request.body()
    body = assemble_spreads(request.app.state.store, settings)
    if body is None:
        return data_unavailable()
    return body


def _parse_asof(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.post("/v1/nowcast/asof", summary="Historical asOf snapshot", tags=["nowcast"])
async def asof(request: Request):
    settings: Settings = request.app.state.settings
    raw = await request.body()
    try:
        payload = parse_json_body(raw, AsofRequest)
    except Exception as exc:
        return error_response(400, "invalid_request", str(exc))
    assert isinstance(payload, AsofRequest)
    if not (payload.asOf or "").strip():
        return error_response(400, "invalid_request", "asOf is required.")
    pinned = _parse_asof(payload.asOf.strip())
    if pinned is None:
        return error_response(400, "invalid_request", "asOf must be ISO-8601.")
    body = assemble_asof(request.app.state.store, settings, pinned)
    if body is None:
        return error_response(
            404,
            "asof_not_found",
            "No observation at or before asOf.",
        )
    return body
