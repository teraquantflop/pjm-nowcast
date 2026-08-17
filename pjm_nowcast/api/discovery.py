"""Service card and discovery metadata. Descriptive surface only."""

from __future__ import annotations

from pathlib import Path

from pjm_nowcast import DISCLAIMER, __version__
from pjm_nowcast.settings import Settings

DEMO_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "demo" / "sample.json"

WHAT_IT_IS = (
    "Trailing and semi-live descriptive statistics on PJM RTO LMP, "
    "selected zonal LMP price spreads, and RTO load."
)
WHAT_IT_IS_NOT = (
    "Not a forecast, signal, trading recommendation, or advice. "
    "Not a substitute for official PJM data products. "
    "Buyer beware: figures are aggregated from public market sources; "
    "freshness equals the last successful background poll."
)

TAGS = ["pjm", "lmp", "load", "spread", "electricity"]


def load_demo_sample() -> dict:
    import json

    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def service_card(settings: Settings) -> dict:
    base = settings.public_base_url.rstrip("/")
    prices = {
        "POST /v1/nowcast/latest": settings.price_l1,
        "POST /v1/nowcast/history": settings.price_l2,
        "POST /v1/nowcast/history/extended": settings.price_l3,
    }
    pay_to = {}
    if settings.evm_pay_to:
        pay_to["eip155:8453"] = settings.evm_pay_to
    if settings.svm_pay_to:
        pay_to["solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"] = settings.svm_pay_to

    latest_schema = {
        "type": "object",
        "properties": {
            "families": {
                "type": "array",
                "items": {"enum": ["rto_lmp", "zonal_spread", "rto_load"]},
                "description": "Optional subset. Default: all families.",
            }
        },
        "additionalProperties": False,
    }
    history_schema = {
        "type": "object",
        "properties": {
            "families": latest_schema["properties"]["families"],
            "windowHours": {
                "type": "integer",
                "minimum": 1,
                "maximum": 72,
                "description": "Trailing window in hours. Default 24. L2 max 72.",
            },
        },
        "additionalProperties": False,
    }
    extended_schema = {
        "type": "object",
        "properties": {
            "families": latest_schema["properties"]["families"],
            "windowHours": {
                "type": "integer",
                "minimum": 1,
                "maximum": settings.l3_max_hours,
                "description": (
                    f"Trailing window in hours. Default 168. Max {settings.l3_max_hours}."
                ),
            },
            "resolution": {"enum": ["native", "hourly"]},
            "compare": {"enum": ["none", "prior_period"]},
        },
        "additionalProperties": False,
    }

    output_fields = (
        "asOf, polledAt, ageSeconds, maxAgeSeconds, stale, observationCount, "
        "and per-family last/min/max/mean/std/p05/p50/p95 with units. "
        "Load also includes sourcePublishedPeakTodayMw / Tomorrow and vsPublishedPeakTodayMw "
        "(source-published figures, not produced by this service)."
    )

    return {
        "name": "pjm-nowcast",
        "version": __version__,
        "description": WHAT_IT_IS,
        "whatItIsNot": WHAT_IT_IS_NOT,
        "disclaimer": DISCLAIMER,
        "publicBaseUrl": base,
        "tags": TAGS,
        "iconUrl": settings.public_icon_url or f"{base}/favicon.ico",
        "timezone": "America/New_York",
        "networks": settings.network_list,
        "facilitators": settings.facilitator_status(),
        "payTo": pay_to,
        "prices": prices,
        "mcp": {"enabled": settings.mcp_enabled, "path": settings.mcp_path}
        if settings.mcp_enabled
        else None,
        "staleness": {
            "asOf": "Observation clock of the latest stored sample (America/New_York).",
            "polledAt": "Wall time the background poller wrote that sample.",
            "ageSeconds": "Seconds since polledAt.",
            "maxAgeSeconds": settings.stale_after_seconds,
            "stale": "true when ageSeconds > maxAgeSeconds. Payload is still returned.",
        },
        "retentionDays": settings.retention_days,
        "endpoints": [
            {
                "tier": "L0",
                "method": "GET",
                "path": "/health",
                "price": "free",
                "description": "Process, store, and poll freshness. No market fetch.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/",
                "price": "free",
                "description": "This service card.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/v1/demo/sample",
                "price": "free",
                "description": "Fixed sample payload. Does not read the live store.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/openapi.json",
                "price": "free",
                "description": "OpenAPI 3 document. Free routes use security: []. Paid nowcast POSTs include x-payment-info and 402.",
            },
            {
                "tier": "L1",
                "method": "POST",
                "path": "/v1/nowcast/latest",
                "price": settings.price_l1,
                "description": (
                    "Latest snapshot plus trailing 24h descriptive stats. " + output_fields
                ),
                "inputSchema": latest_schema,
                "exampleRequest": {"families": ["rto_lmp", "zonal_spread", "rto_load"]},
            },
            {
                "tier": "L2",
                "method": "POST",
                "path": "/v1/nowcast/history",
                "price": settings.price_l2,
                "description": (
                    "1–72h history of the same families at native poll resolution. "
                    + output_fields
                ),
                "inputSchema": history_schema,
                "exampleRequest": {"families": ["rto_lmp"], "windowHours": 24},
            },
            {
                "tier": "L3",
                "method": "POST",
                "path": "/v1/nowcast/history/extended",
                "price": settings.price_l3,
                "description": (
                    f"Up to {settings.max_history_days}-day history, optional hourly "
                    "buckets and prior-period comparison. Descriptive only. "
                    + output_fields
                ),
                "inputSchema": extended_schema,
                "exampleRequest": {
                    "families": ["rto_load"],
                    "windowHours": 168,
                    "resolution": "hourly",
                    "compare": "prior_period",
                },
            },
        ],
    }
