"""Stateless Streamable-HTTP MCP façade. Paid tools use the same 402 rules."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from pjm_nowcast import DISCLAIMER, __version__
from pjm_nowcast.api.discovery import health_payload, load_demo_sample, mcp_mount, service_card
from pjm_nowcast.payments.gate import payment_required_payload
from pjm_nowcast.payments.optionbook import HEADER as OPTIONBOOK_HEADER
from pjm_nowcast.payments.optionbook import header_matches
from pjm_nowcast.payments.routes import price_for
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.assemble import assemble_history, assemble_latest

router = APIRouter(include_in_schema=False)

_FAMILIES = {
    "type": "array",
    "items": {"enum": ["rto_lmp", "zonal_spread", "rto_load"]},
    "description": "Optional subset. Default: all three families.",
}

_PAYLOAD_BLURB = (
    "Returns descriptive last/min/max/mean/std/p05/p50/p95 for RTO LMP (USD/MWh), "
    "zonal LMP spread (USD/MWh, plus zone map), and/or RTO load (MW), with "
    "asOf, polledAt, ageSeconds, stale. Trailing mean/std is a descriptive mix of "
    "the stored sample, not a live forecast F. Not a forecast. "
)

_PAID_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "paymentStatus": {"enum": ["paid", "required"]},
        "error": {"type": "string"},
        "paymentRequired": {
            "type": "object",
            "description": "Same 402 challenge body as HTTP PAYMENT-REQUIRED (decoded).",
        },
        "disclaimer": {"type": "string"},
        "product": {"type": "string"},
        "asOf": {"type": "string"},
        "polledAt": {"type": "string"},
        "stale": {"type": "boolean"},
        "rtoLmp": {"type": "object"},
        "zonalSpread": {"type": "object"},
        "rtoLoad": {"type": "object"},
    },
}

_FREE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"paymentStatus": {"enum": ["free"]}},
}


def _paid_description(settings: Settings, path: str, lead: str) -> str:
    price = price_for(path, settings)
    nets = ", ".join(settings.network_list)
    return (
        lead
        + _PAYLOAD_BLURB
        + DISCLAIMER
        + f" Payment: x402 exact USDC on {nets}. Price {price}. "
        "Without payment the tool result is paymentStatus=required plus a "
        "paymentRequired 402 body (same facilitator/terms as HTTP POST of this path). "
        "HTTP POST of the matching route still returns 402."
    )


def _x402_meta(settings: Settings, path: str) -> dict[str, Any]:
    return {
        "scheme": "exact",
        "asset": "USDC",
        "price": price_for(path, settings),
        "networks": list(settings.network_list),
        "httpPath": path,
        "unpaid": "paymentStatus=required and paymentRequired in the tool result",
    }


def tool_catalog(settings: Settings) -> list[dict[str, Any]]:
    """MCP tools 1:1 with product HTTP routes. No payTo on the catalog."""
    return [
        {
            "name": "health",
            "description": (
                "Free. Same as GET /health: process, store, poll freshness. "
                "No market fetch. paymentStatus=free."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": _FREE_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": False,
            "http_path": "/health",
        },
        {
            "name": "service_info",
            "description": (
                "Free service card (GET /): what pjm-nowcast is and is not, "
                "networks, prices, schemas, MCP URL, staleness fields. paymentStatus=free."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": _FREE_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": False,
            "http_path": "/",
        },
        {
            "name": "demo_sample",
            "description": (
                "Free fixed sample payload (GET /v1/demo/sample). "
                "Does not read the live store. paymentStatus=free."
            ),
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": _FREE_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": False,
            "http_path": "/v1/demo/sample",
        },
        {
            "name": "nowcast_latest",
            "description": _paid_description(
                settings,
                "/v1/nowcast/latest",
                "POST /v1/nowcast/latest. Latest stored snapshot plus trailing 24h stats. "
                "Also top-level last price_vol ($/MWh rolling realized LMP std from "
                "the last 8 SQLite prints, RMS of successive diffs, not Black vol) "
                "and price_vol_missing. ",
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"families": _FAMILIES},
                "additionalProperties": False,
            },
            "outputSchema": _PAID_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": True,
            "http_path": "/v1/nowcast/latest",
        },
        {
            "name": "nowcast_history",
            "description": _paid_description(
                settings,
                "/v1/nowcast/history",
                "POST /v1/nowcast/history. 1–72h descriptive history at native poll resolution. ",
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "families": _FAMILIES,
                    "windowHours": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 72,
                        "description": "Trailing window in hours. Default 24. Not required.",
                    },
                },
                "additionalProperties": False,
            },
            "outputSchema": _PAID_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": True,
            "http_path": "/v1/nowcast/history",
        },
        {
            "name": "nowcast_history_extended",
            "description": _paid_description(
                settings,
                "/v1/nowcast/history/extended",
                "POST /v1/nowcast/history/extended. Extended history within retention; "
                "optional hourly buckets and prior-period comparison. ",
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "families": _FAMILIES,
                    "windowHours": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Trailing window in hours. Default 168. Not required.",
                    },
                    "resolution": {"enum": ["native", "hourly"]},
                    "compare": {"enum": ["none", "prior_period"]},
                },
                "additionalProperties": False,
            },
            "outputSchema": _PAID_OUTPUT_SCHEMA,
            "annotations": {"readOnlyHint": True},
            "paid": True,
            "http_path": "/v1/nowcast/history/extended",
        },
    ]


def _public_tool(settings: Settings, tool: dict[str, Any]) -> dict[str, Any]:
    out = {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["inputSchema"],
    }
    if tool.get("outputSchema"):
        out["outputSchema"] = tool["outputSchema"]
    if tool.get("annotations"):
        out["annotations"] = tool["annotations"]
    if tool.get("paid"):
        out["_meta"] = {"x402": _x402_meta(settings, tool["http_path"])}
    return out


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


@router.get("")
@router.get("/")
def mcp_discover(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    mount = mcp_mount(settings) or {
        "enabled": False,
        "path": settings.mcp_path,
        "url": f"{settings.public_base_url.rstrip('/')}{settings.mcp_path}",
        "transport": "streamable-http",
        "protocolVersion": "2024-11-05",
    }
    return {
        "name": "pjm-nowcast",
        "version": __version__,
        "transport": "streamable-http",
        "protocolVersion": "2024-11-05",
        "url": mount["url"],
        "methods": ["initialize", "ping", "tools/list", "tools/call"],
        "note": (
            "POST JSON-RPC to this URL. tools/list is free and needs no key. "
            "Paid nowcast tools return paymentStatus=required without x402 payment."
        ),
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
        return JSONResponse([_handle(request, settings, m) for m in msg])
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
                "serverInfo": {"name": "pjm-nowcast", "version": __version__},
            },
        )
    if method == "notifications/initialized":
        return _ok(mid, {})
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        tools = [_public_tool(settings, t) for t in tool_catalog(settings)]
        return _ok(mid, {"tools": tools})
    if method == "tools/call":
        return _ok(mid, _call_tool(request, settings, params))
    return _err(mid, -32601, f"Method not found: {method}")


def _has_mcp_payment(
    request: Request, settings: Settings, params: dict[str, Any]
) -> bool:
    headers = {k.lower(): v for k, v in request.headers.items()}
    if header_matches(settings.optionbook_id, headers.get(OPTIONBOOK_HEADER)):
        return True
    if any(headers.get(h) for h in ("payment-signature", "x-payment", "x-payment-signature")):
        return True
    meta = params.get("_meta") or {}
    return bool(meta.get("x402/payment"))


def _with_status(body: dict[str, Any], status: str) -> dict[str, Any]:
    if "paymentStatus" not in body:
        return {**body, "paymentStatus": status}
    return body


def _call_tool(request: Request, settings: Settings, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    args = params.get("arguments") or {}
    tool = next((t for t in tool_catalog(settings) if t["name"] == name), None)
    if tool is None:
        return _text_result({"error": "unknown_tool", "name": name}, is_error=True)

    if tool.get("paid") and not settings.x402_disabled:
        if not _has_mcp_payment(request, settings, params):
            path = tool["http_path"]
            required = payment_required_payload(settings, path)
            return _text_result(
                {
                    "error": "Payment required",
                    "paymentStatus": "required",
                    "paymentRequired": required,
                    "disclaimer": DISCLAIMER,
                },
                is_error=True,
            )

    store = request.app.state.store
    if name == "health":
        return _text_result(_with_status(health_payload(settings, store), "free"))
    if name == "service_info":
        return _text_result(_with_status(service_card(settings), "free"))
    if name == "demo_sample":
        if not settings.free_demo_enabled:
            return _text_result({"error": "not_found"}, is_error=True)
        return _text_result(_with_status(load_demo_sample(), "free"))
    if name == "nowcast_latest":
        body = assemble_latest(store, settings, families=args.get("families"))
        if body is None:
            return _text_result({"error": "data_unavailable"}, is_error=True)
        return _text_result(_with_status(body, "paid"))
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
        return _text_result(_with_status(body, "paid"))
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
        return _text_result(_with_status(body, "paid"))
    return _text_result({"error": "unknown_tool"}, is_error=True)
