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

# Free discovery surfaces (not new paid URLs).
FREE_DISCOVERY_PATHS = (
    "/",
    "/health",
    "/openapi.json",
    "/swagger.json",
    "/llms.txt",
    "/.well-known/x402",
    "/.well-known/x402.json",
    "/skill.md",
    "/SKILL.md",
    "/robots.txt",
    "/v1/discovery",
    "/v1/demo/sample",
)


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
                "tier": "L0",
                "method": "GET",
                "path": "/swagger.json",
                "price": "free",
                "description": "Alias of /openapi.json.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/skill.md",
                "price": "free",
                "description": "Short agent skill card (also /SKILL.md).",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/llms.txt",
                "price": "free",
                "description": "Plain-text discovery index.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/.well-known/x402",
                "price": "free",
                "description": "x402 well-known catalog (also /.well-known/x402.json).",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/robots.txt",
                "price": "free",
                "description": "Allows free discovery paths.",
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


def skill_markdown(settings: Settings) -> str:
    base = settings.public_base_url.rstrip("/")
    return "\n".join(
        [
            "# pjm-nowcast",
            "",
            "PJM RTO nowcast: latest load, RTO LMP, and zonal LMPs from public page ingest.",
            "Descriptive statistics only. Not a forecast, signal, or trading recommendation.",
            "",
            f"Base URL: {base}",
            "",
            "Pay: x402 exact USDC on Solana and Base. Unpaid paid routes return HTTP 402 with a PAYMENT-REQUIRED header.",
            "",
            "Free:",
            "- GET /",
            "- GET /health",
            "- GET /openapi.json",
            "- GET /swagger.json",
            "- GET /llms.txt",
            "- GET /.well-known/x402",
            "",
            "Paid (existing catalog):",
            f"- POST /v1/nowcast/latest — {settings.price_l1}",
            f"- POST /v1/nowcast/history — {settings.price_l2}",
            f"- POST /v1/nowcast/history/extended — {settings.price_l3}",
            "",
            "Example paid request:",
            "",
            "```json",
            '{"families": ["rto_lmp", "zonal_spread", "rto_load"]}',
            "```",
            "",
            "On 402, decode PAYMENT-REQUIRED, settle x402 exact USDC, retry the same POST with PAYMENT-SIGNATURE.",
            "",
            f"OpenAPI: {base}/openapi.json",
            "",
        ]
    )


def llms_txt(settings: Settings) -> str:
    base = settings.public_base_url.rstrip("/")
    lines = [
        "# pjm-nowcast",
        "",
        WHAT_IT_IS,
        "",
        f"Base: {base}",
        "",
        "## Free discovery",
    ]
    for path in FREE_DISCOVERY_PATHS:
        lines.append(f"- GET {path}")
    lines.extend(
        [
            "",
            "## Paid",
            f"- POST /v1/nowcast/latest — {settings.price_l1}",
            f"- POST /v1/nowcast/history — {settings.price_l2}",
            f"- POST /v1/nowcast/history/extended — {settings.price_l3}",
            "",
            f"Docs: {base}/openapi.json {base}/skill.md",
            "",
        ]
    )
    return "\n".join(lines)


def robots_txt() -> str:
    lines = ["User-agent: *", "Allow: /"]
    for path in FREE_DISCOVERY_PATHS:
        if path != "/":
            lines.append(f"Allow: {path}")
    lines.append("")
    return "\n".join(lines)


def well_known_x402(settings: Settings) -> dict:
    """Catalog extras for agents. No payTo / wallets."""
    base = settings.public_base_url.rstrip("/")
    return {
        "x402Version": 2,
        "name": "pjm-nowcast",
        "description": WHAT_IT_IS,
        "url": base,
        "openapi": f"{base}/openapi.json",
        "swagger": f"{base}/swagger.json",
        "skill": f"{base}/skill.md",
        "llms": f"{base}/llms.txt",
        "networks": list(settings.network_list),
        "facilitators": settings.facilitator_status(),
        "resources": [
            {
                "url": f"{base}/v1/nowcast/latest",
                "method": "POST",
                "price": settings.price_l1,
                "description": "Latest load, RTO LMP, and zonal LMP descriptive snapshot.",
            },
            {
                "url": f"{base}/v1/nowcast/history",
                "method": "POST",
                "price": settings.price_l2,
                "description": "1–72h descriptive history.",
            },
            {
                "url": f"{base}/v1/nowcast/history/extended",
                "method": "POST",
                "price": settings.price_l3,
                "description": "Extended descriptive history within retention.",
            },
        ],
        "free": [
            f"{base}{p}"
            for p in (
                "/",
                "/health",
                "/openapi.json",
                "/swagger.json",
                "/llms.txt",
                "/.well-known/x402",
            )
        ],
    }
