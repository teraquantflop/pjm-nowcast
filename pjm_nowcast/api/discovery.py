"""Service card and discovery metadata. Descriptive surface only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pjm_nowcast import DISCLAIMER, __version__
from pjm_nowcast.payments.routes import PAID_DESCRIPTIONS, PAID_ROUTES, pay_to_by_network, price_for
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
    "/llm.txt",
    "/.well-known/x402",
    "/.well-known/x402.json",
    "/.well-known/agent.json",
    "/.well-known/x402-resources",
    "/.well-known/llms.txt",
    "/.well-known/llm.txt",
    "/skill.md",
    "/SKILL.md",
    "/robots.txt",
    "/v1/discovery",
    "/v1/demo/sample",
)

# Agent-facing only (llms.txt / skill.md). Keep off GET / — isolation tests.
AGENT_NOTES = (
    "Paid payloads are descriptive last/min/max/mean/std/percentiles for RTO LMP "
    "(USD/MWh), zonal LMP spread (USD/MWh, plus zone map), and RTO load (MW), "
    "with asOf/polledAt/stale. Trailing mean/std is a mix of the stored sample, "
    "not a live forecast F. Do not treat that mix as live F while entropy is near "
    "ln(5) (~1.609); the internal mixture is then uninformative. "
    "POST /v1/nowcast/latest and MCP nowcast_latest also return last price_vol "
    "($/MWh rolling realized LMP std over the last 8 prints, RMS of successive "
    "diffs — same formula as the poller, not annualized Black vol, not "
    "rtoLmp.std / mix std) and price_vol_missing. After restart, last price_vol "
    "is rebuilt from those SQLite RTO LMP diffs when the in-memory window is "
    "empty. When vol is missing, non-finite, or <= 0, price_vol_missing is true "
    "and price_vol is null. Latest also returns mix_std_price ($/MWh HMM mixture "
    "std of RTO LMP) and mix_n_obs from mix.json; that is not price_vol. "
    "high-spread is an internal zonal flag, not returned "
    "on HTTP/MCP nowcast bodies."
)


def load_demo_sample() -> dict:
    import json

    return json.loads(DEMO_PATH.read_text(encoding="utf-8"))


def public_base(settings: Settings) -> str:
    return settings.public_base_url.rstrip("/")


def mcp_mount(settings: Settings) -> dict[str, Any] | None:
    if not settings.mcp_enabled:
        return None
    path = settings.mcp_path if settings.mcp_path.startswith("/") else f"/{settings.mcp_path}"
    return {
        "enabled": True,
        "path": path,
        "url": f"{public_base(settings)}{path}",
        "transport": "streamable-http",
        "protocolVersion": "2024-11-05",
    }


def health_payload(settings: Settings, store: Any) -> dict[str, Any]:
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
        "networks": list(settings.network_list),
        "payToByNetwork": pay_to_by_network(settings),
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


def service_card(settings: Settings) -> dict:
    base = public_base(settings)
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

    card = {
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
        "payToByNetwork": pay_to_by_network(settings),
        "facilitators": settings.facilitator_status(),
        "prices": prices,
        "mcp": mcp_mount(settings),
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
                "description": "Plain-text discovery index (also /llm.txt, /.well-known/llms.txt).",
            },
            {
                "tier": "L0",
                "method": "POST",
                "path": settings.mcp_path,
                "price": "free",
                "description": (
                    "Streamable HTTP MCP JSON-RPC. tools/list is free. "
                    "Paid nowcast tools return paymentStatus=required without x402."
                ),
            }
            if settings.mcp_enabled
            else None,
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
                "path": "/.well-known/agent.json",
                "price": "free",
                "description": "Agent card: name, paid tools, networks, facilitator.",
            },
            {
                "tier": "L0",
                "method": "GET",
                "path": "/.well-known/x402-resources",
                "price": "free",
                "description": "Machine list of paid resources (method, path, price, networks).",
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
                    "Latest snapshot plus trailing 24h descriptive stats. "
                    "Also last price_vol ($/MWh rolling realized LMP std, not Black vol), "
                    "price_vol_missing, mix_std_price (mixture std of RTO LMP, not price_vol), "
                    "and mix_n_obs. "
                    + output_fields
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
    card["endpoints"] = [e for e in card["endpoints"] if e]
    return card


def skill_markdown(settings: Settings) -> str:
    base = public_base(settings)
    mcp = mcp_mount(settings)
    mcp_line = f"MCP: POST {mcp['url']} (Streamable HTTP JSON-RPC). No key for tools/list." if mcp else "MCP: disabled."
    return "\n".join(
        [
            "# pjm-nowcast",
            "",
            "PJM RTO nowcast: latest load, RTO LMP, and zonal LMPs from public page ingest.",
            "Descriptive statistics only. Not a forecast, signal, or trading recommendation.",
            "",
            f"Base URL: {base}",
            mcp_line,
            "",
            "Pay: x402 exact USDC on Solana, Base, and Polygon. Unpaid paid routes return HTTP 402 with a PAYMENT-REQUIRED header. Unpaid MCP paid tools return paymentStatus=required and the same paymentRequired body.",
            "",
            "Free:",
            "- GET /",
            "- GET /health",
            "- GET /openapi.json",
            "- GET /swagger.json",
            "- GET /llms.txt",
            "- GET /llm.txt",
            "- GET /.well-known/x402",
            "- GET /.well-known/llms.txt",
            "",
            "Paid (existing catalog):",
            f"- POST /v1/nowcast/latest — {settings.price_l1} — MCP tool nowcast_latest",
            f"- POST /v1/nowcast/history — {settings.price_l2} — MCP tool nowcast_history",
            f"- POST /v1/nowcast/history/extended — {settings.price_l3} — MCP tool nowcast_history_extended",
            "",
            "Example paid request:",
            "",
            "```json",
            '{"families": ["rto_lmp", "zonal_spread", "rto_load"]}',
            "```",
            "",
            "On 402, decode PAYMENT-REQUIRED, settle x402 exact USDC, retry the same POST with PAYMENT-SIGNATURE.",
            "",
            AGENT_NOTES,
            "",
            f"OpenAPI: {base}/openapi.json",
            "",
        ]
    )


def llms_txt(settings: Settings) -> str:
    base = public_base(settings)
    mcp = mcp_mount(settings)
    lines = [
        "# pjm-nowcast",
        "",
        WHAT_IT_IS,
        "",
        f"Base: {base}",
        "",
        "## MCP",
    ]
    if mcp:
        lines.extend(
            [
                f"- Transport: Streamable HTTP JSON-RPC",
                f"- URL: {mcp['url']}",
                "- Connect: POST JSON-RPC (`initialize`, `tools/list`, `tools/call`). No API key for discovery.",
                "- Free tools: health, service_info, demo_sample",
                "- Paid tools: nowcast_latest, nowcast_history, nowcast_history_extended (x402 exact USDC; unpaid → paymentStatus=required)",
            ]
        )
    else:
        lines.append("- disabled")
    lines.extend(
        [
            "",
            "## Free discovery",
        ]
    )
    for path in FREE_DISCOVERY_PATHS:
        lines.append(f"- GET {path}")
    lines.extend(
        [
            "",
            "## Paid (x402 exact USDC, Solana + Base)",
            f"- POST /v1/nowcast/latest — {settings.price_l1} — MCP nowcast_latest",
            f"- POST /v1/nowcast/history — {settings.price_l2} — MCP nowcast_history",
            f"- POST /v1/nowcast/history/extended — {settings.price_l3} — MCP nowcast_history_extended",
            "",
            "## Notes",
            AGENT_NOTES,
            "",
            f"Docs: {base}/openapi.json {base}/skill.md {base}/.well-known/x402",
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
    base = public_base(settings)
    mcp = mcp_mount(settings)
    free_paths = (
        "/",
        "/health",
        "/openapi.json",
        "/swagger.json",
        "/llms.txt",
        "/llm.txt",
        "/.well-known/x402",
        "/.well-known/agent.json",
        "/.well-known/x402-resources",
        "/.well-known/llms.txt",
        "/.well-known/llm.txt",
        "/skill.md",
    )
    out = {
        "x402Version": 2,
        "name": "pjm-nowcast",
        "description": WHAT_IT_IS,
        "url": base,
        "openapi": f"{base}/openapi.json",
        "swagger": f"{base}/swagger.json",
        "skill": f"{base}/skill.md",
        "llms": f"{base}/llms.txt",
        "llm": f"{base}/llm.txt",
        "scheme": "exact",
        "asset": "USDC",
        "networks": list(settings.network_list),
        "payToByNetwork": pay_to_by_network(settings),
        "facilitators": settings.facilitator_status(),
        "mcp": mcp,
        "resources": [
            {
                "url": f"{base}/v1/nowcast/latest",
                "method": "POST",
                "price": settings.price_l1,
                "mcpTool": "nowcast_latest",
                "description": "Latest load, RTO LMP, and zonal LMP descriptive snapshot.",
            },
            {
                "url": f"{base}/v1/nowcast/history",
                "method": "POST",
                "price": settings.price_l2,
                "mcpTool": "nowcast_history",
                "description": "1–72h descriptive history.",
            },
            {
                "url": f"{base}/v1/nowcast/history/extended",
                "method": "POST",
                "price": settings.price_l3,
                "mcpTool": "nowcast_history_extended",
                "description": "Extended descriptive history within retention.",
            },
        ],
        "free": [f"{base}{p}" for p in free_paths],
    }
    if mcp:
        out["free"] = list(out["free"]) + [mcp["url"]]
    return out


def agent_card(settings: Settings) -> dict[str, Any]:
    base = public_base(settings)
    mcp = mcp_mount(settings)
    tools = [
        {
            "name": "health",
            "method": "GET",
            "path": "/health",
            "price": "free",
            "paid": False,
        },
        {
            "name": "nowcast_latest",
            "method": "POST",
            "path": "/v1/nowcast/latest",
            "price": settings.price_l1,
            "paid": True,
        },
        {
            "name": "nowcast_history",
            "method": "POST",
            "path": "/v1/nowcast/history",
            "price": settings.price_l2,
            "paid": True,
        },
        {
            "name": "nowcast_history_extended",
            "method": "POST",
            "path": "/v1/nowcast/history/extended",
            "price": settings.price_l3,
            "paid": True,
        },
    ]
    return {
        "name": "pjm-nowcast",
        "description": WHAT_IT_IS,
        "version": __version__,
        "url": base,
        "facilitator": settings.facilitator_url,
        "networks": list(settings.network_list),
        "payToByNetwork": pay_to_by_network(settings),
        "mcp": mcp,
        "tools": tools,
    }


def x402_resources(settings: Settings) -> dict[str, Any]:
    schemas = {
        "/v1/nowcast/latest": {
            "families": "optional array of rto_lmp | zonal_spread | rto_load",
        },
        "/v1/nowcast/history": {
            "families": "optional",
            "windowHours": "1–72, default 24",
        },
        "/v1/nowcast/history/extended": {
            "families": "optional",
            "windowHours": f"1–{settings.l3_max_hours}, default 168",
            "resolution": "native | hourly",
            "compare": "none | prior_period",
        },
    }
    resources = []
    for path in PAID_ROUTES:
        resources.append(
            {
                "method": "POST",
                "path": path,
                "price": price_for(path, settings),
                "scheme": "exact",
                "asset": "USDC",
                "networks": list(settings.network_list),
                "payToByNetwork": pay_to_by_network(settings),
                "description": PAID_DESCRIPTIONS.get(path, ""),
                "inputSchema": schemas.get(path, {}),
            }
        )
    return {
        "x402Version": 2,
        "url": public_base(settings),
        "facilitator": settings.facilitator_url,
        "resources": resources,
    }
