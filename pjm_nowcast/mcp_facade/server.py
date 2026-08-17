"""Stateless Streamable-HTTP MCP façade. Paid tools use the same 402 rules."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.api.discovery import load_demo_sample, service_card
from pjm_nowcast.payments.gate import payment_required_payload
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.assemble import assemble_history, assemble_latest

router = APIRouter(include_in_schema=False)


TOOLS = [
    {
        "name": "service_info",
        "description": (
            "Free service card: what pjm-nowcast is and is not, networks, "
            "prices, schemas, and staleness fields."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "paid": False,
    },
    {
        "name": "demo_sample",
        "description": "Free fixed sample payload. Does not read live store.",
        "inputSchema": {"type": "object", "properties": {}},
        "paid": False,
    },
    {
        "name": "nowcast_latest",
        "description": (
            "Latest descriptive snapshot of RTO LMP, zonal LMP spreads, and "
            "RTO load, plus trailing 24h stats. Not a forecast. "
            + DISCLAIMER
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "families": {
                    "type": "array",
                    "items": {"enum": ["rto_lmp", "zonal_spread", "rto_load"]},
                }
            },
        },
        "paid": True,
        "http_path": "/v1/nowcast/latest",
    },
    {
        "name": "nowcast_history",
        "description": (
            "1–72 hour descriptive history of the same families. Not a forecast. "
            + DISCLAIMER
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "families": {
                    "type": "array",
                    "items": {"enum": ["rto_lmp", "zonal_spread", "rto_load"]},
                },
                "windowHours": {"type": "integer", "minimum": 1, "maximum": 72},
            },
        },
        "paid": True,
        "http_path": "/v1/nowcast/history",
    },
    {
        "name": "nowcast_history_extended",
        "description": (
            "Extended descriptive history within the retention window, optional "
            "hourly buckets and prior-period comparison. Not a forecast. "
            + DISCLAIMER
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "families": {
                    "type": "array",
                    "items": {"enum": ["rto_lmp", "zonal_spread", "rto_load"]},
                },
                "windowHours": {"type": "integer", "minimum": 1},
                "resolution": {"enum": ["native", "hourly"]},
                "compare": {"enum": ["none", "prior_period"]},
            },
        },
        "paid": True,
        "http_path": "/v1/nowcast/history/extended",
    },
]


def mcp_router() -> APIRouter:
    return router


def _ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _text_result(payload: Any, is_error: bool = False) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload if isinstance(payload, dict) else {"text": text},
        "isError": is_error,
    }


@router.post("")
@router.post("/")
async def mcp_endpoint(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)

    if isinstance(msg, list):
        return JSONResponse(
            [_handle(request, settings, m) for m in msg]
        )
    return JSONResponse(_handle(request, settings, msg))


def _handle(request: Request, settings: Settings, msg: dict[str, Any]) -> dict[str, Any]:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return _ok(
            mid,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pjm-nowcast", "version": "1.0.0"},
            },
        )
    if method == "notifications/initialized":
        return _ok(mid, {})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in TOOLS
        ]
        return _ok(mid, {"tools": tools})
    if method == "tools/call":
        return _ok(mid, _call_tool(request, settings, params))
    return _err(mid, -32601, f"Method not found: {method}")


def _has_mcp_payment(request: Request, params: dict[str, Any]) -> bool:
    headers = {k.lower(): v for k, v in request.headers.items()}
    if any(headers.get(h) for h in ("payment-signature", "x-payment", "x-payment-signature")):
        return True
    meta = params.get("_meta") or {}
    return bool(meta.get("x402/payment"))


def _call_tool(request: Request, settings: Settings, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        return _text_result({"error": "unknown_tool", "name": name}, is_error=True)

    if tool.get("paid") and not settings.x402_disabled:
        if not _has_mcp_payment(request, params):
            path = tool["http_path"]
            required = payment_required_payload(settings, path)
            return _text_result(
                {
                    "error": "Payment required",
                    "paymentRequired": required,
                    "disclaimer": DISCLAIMER,
                },
                is_error=True,
            )

    store = request.app.state.store
    if name == "service_info":
        return _text_result(service_card(settings))
    if name == "demo_sample":
        if not settings.free_demo_enabled:
            return _text_result({"error": "not_found"}, is_error=True)
        return _text_result(load_demo_sample())
    if name == "nowcast_latest":
        body = assemble_latest(store, settings, families=args.get("families"))
        if body is None:
            return _text_result({"error": "data_unavailable"}, is_error=True)
        return _text_result(body)
    if name == "nowcast_history":
        hours = int(args.get("windowHours") or 24)
        if hours < 1 or hours > settings.l2_max_hours:
            return _text_result(
                {"error": "invalid_request", "message": "windowHours out of L2 range"},
                is_error=True,
            )
        body = assemble_history(
            store,
            settings,
            window_hours=hours,
            families=args.get("families"),
        )
        if body is None:
            return _text_result({"error": "data_unavailable"}, is_error=True)
        return _text_result(body)
    if name == "nowcast_history_extended":
        hours = int(args.get("windowHours") or 168)
        if hours < 1 or hours > settings.l3_max_hours:
            return _text_result(
                {"error": "invalid_request", "message": "windowHours out of L3 range"},
                is_error=True,
            )
        body = assemble_history(
            store,
            settings,
            window_hours=hours,
            families=args.get("families"),
            resolution=args.get("resolution") or "native",
            compare=args.get("compare") or "none",
        )
        if body is None:
            return _text_result({"error": "data_unavailable"}, is_error=True)
        return _text_result(body)
    return _text_result({"error": "unknown_tool"}, is_error=True)
