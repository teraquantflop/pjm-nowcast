"""OpenAPI 3 document for GET /openapi.json.

Free routes advertise security: []. Only the three paid nowcast POSTs
carry x-payment-info and 402 responses. Prices, pay-to addresses,
networks, and facilitator are read from existing settings — not redefined.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from pjm_nowcast import DISCLAIMER, __version__
from pjm_nowcast.api.discovery import WHAT_IT_IS, WHAT_IT_IS_NOT
from pjm_nowcast.api.schemas import (
    ExtendedHistoryRequest,
    HistoryRequest,
    LatestRequest,
)
from pjm_nowcast.payments.gate import payment_required_payload
from pjm_nowcast.payments.routes import PAID_ROUTES, price_for
from pjm_nowcast.settings import Settings

FREE_PATHS = {
    "/",
    "/health",
    "/v1/demo/sample",
    "/v1/discovery",
    "/openapi.json",
    "/swagger.json",
    "/llms.txt",
    "/.well-known/x402",
    "/.well-known/agent.json",
    "/.well-known/x402-resources",
}

PAID_PATHS = frozenset(PAID_ROUTES)

PAID_SUMMARIES = {
    "/v1/nowcast/latest": "Latest descriptive snapshot (24h trailing stats)",
    "/v1/nowcast/history": "1–72h descriptive history",
    "/v1/nowcast/history/extended": "Extended descriptive history within retention",
}

PAID_DESCRIPTIONS = {
    "/v1/nowcast/latest": (
        "Latest stored sample plus trailing 24h descriptive stats for RTO LMP, "
        "zonal LMP spreads, and RTO load. Not a forecast. Unpaid requests "
        "receive 402 with a PAYMENT-REQUIRED header."
    ),
    "/v1/nowcast/history": (
        "1–72 hour descriptive history at native poll resolution. "
        "Not a forecast. Unpaid requests receive 402 with a PAYMENT-REQUIRED header."
    ),
    "/v1/nowcast/history/extended": (
        "History up to the configured retention window, with optional hourly "
        "buckets and prior-period comparison. Descriptive only. Unpaid requests "
        "receive 402 with a PAYMENT-REQUIRED header."
    ),
}

_REQUEST_MODELS = {
    "/v1/nowcast/latest": LatestRequest,
    "/v1/nowcast/history": HistoryRequest,
    "/v1/nowcast/history/extended": ExtendedHistoryRequest,
}


def _catalog_accepts(accepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAPI is a free catalog — omit receiving addresses."""
    out = []
    for item in accepts:
        copy = {k: v for k, v in item.items() if k not in {"payTo", "pay_to"}}
        out.append(copy)
    return out


def payment_info(settings: Settings, path: str) -> dict[str, Any]:
    """Document terms for agents. Wallets stay off this free document."""
    payload = payment_required_payload(settings, path)
    return {
        "scheme": "exact",
        "asset": "USDC",
        "price": price_for(path, settings),
        "facilitator": settings.facilitator_url,
        "networks": list(settings.network_list),
        "resource": payload["resource"],
        "accepts": _catalog_accepts(payload["accepts"]),
    }


def _schema_ref(model: type) -> dict[str, Any]:
    return model.model_json_schema(ref_template="#/components/schemas/{model}")


def _ensure_components(schema: dict[str, Any]) -> dict[str, Any]:
    comps = schema.setdefault("components", {})
    comps.setdefault("schemas", {})
    comps.setdefault("securitySchemes", {})
    comps.setdefault("headers", {})
    comps.setdefault("responses", {})
    return comps


def customize_openapi(schema: dict[str, Any], settings: Settings) -> dict[str, Any]:
    schema["openapi"] = "3.1.0"
    schema["info"] = {
        "title": "pjm-nowcast",
        "version": __version__,
        "description": f"{WHAT_IT_IS} {WHAT_IT_IS_NOT} {DISCLAIMER}",
    }
    schema["servers"] = [{"url": settings.public_base_url.rstrip("/")}]

    comps = _ensure_components(schema)
    comps["securitySchemes"]["x402"] = {
        "type": "apiKey",
        "in": "header",
        "name": "PAYMENT-SIGNATURE",
        "description": (
            "x402 payment proof. Omit on free routes. "
            "On paid routes, missing or invalid payment yields HTTP 402 "
            "and a PAYMENT-REQUIRED header."
        ),
    }
    comps["headers"]["PaymentRequired"] = {
        "description": "Base64-encoded x402 v2 payment requirements.",
        "schema": {"type": "string"},
    }
    comps["responses"]["PaymentRequired"] = {
        "description": (
            "Payment required. Empty or malformed bodies without payment "
            "also receive 402 (not 400). Decode the PAYMENT-REQUIRED header."
        ),
        "headers": {
            "PAYMENT-REQUIRED": {"$ref": "#/components/headers/PaymentRequired"},
        },
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "description": "Typically an empty object; terms are in the header.",
                }
            }
        },
    }
    comps["responses"]["DataUnavailable"] = {
        "description": "No observation is stored yet.",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorBody"}
            }
        },
    }
    comps["schemas"]["ErrorBody"] = {
        "type": "object",
        "properties": {
            "error": {"type": "string"},
            "message": {"type": "string"},
            "disclaimer": {"type": "string"},
        },
        "required": ["error", "message"],
    }
    comps["schemas"]["NowcastEnvelope"] = {
        "type": "object",
        "description": (
            "Descriptive statistics envelope. Fields asOf, polledAt, "
            "ageSeconds, maxAgeSeconds, stale are always present."
        ),
        "properties": {
            "product": {"type": "string"},
            "disclaimer": {"type": "string"},
            "timezone": {"type": "string"},
            "asOf": {"type": "string", "format": "date-time"},
            "polledAt": {"type": "string", "format": "date-time"},
            "ageSeconds": {"type": "integer"},
            "maxAgeSeconds": {"type": "integer"},
            "stale": {"type": "boolean"},
            "observationCount": {"type": "integer"},
            "rtoLmp": {"type": "object"},
            "zonalSpread": {"type": "object"},
            "rtoLoad": {"type": "object"},
            "price_vol": {
                "type": ["number", "null"],
                "description": (
                    "Latest only. Rolling realized LMP std in $/MWh from the "
                    "last 8 SQLite RTO LMP prints (RMS of successive diffs; "
                    "not annualized Black vol, not rtoLmp.std). "
                    "Null when price_vol_missing is true."
                ),
            },
            "price_vol_missing": {"type": "boolean"},
            "mix_std_price": {
                "type": ["number", "null"],
                "description": (
                    "Latest only. Mixture std of RTO LMP in $/MWh from the "
                    "poller mix.json sidecar. Not price_vol and not rtoLmp.std."
                ),
            },
            "mix_n_obs": {
                "type": ["integer", "null"],
                "description": "Latest only. Observation count paired with mix_std_price.",
            },
            "windowHours": {"type": "integer"},
            "resolution": {"type": "string"},
            "priorPeriod": {"type": "object"},
        },
    }
    for name, model in (
        ("LatestRequest", LatestRequest),
        ("HistoryRequest", HistoryRequest),
        ("ExtendedHistoryRequest", ExtendedHistoryRequest),
    ):
        comps["schemas"][name] = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )

    # Global default: paid. Free paths override with security: [].
    schema["security"] = [{"x402": []}]

    paths = schema.get("paths") or {}
    # Drop MCP (and any other non-public) operations from the published spec.
    for path in list(paths):
        if path == settings.mcp_path or path.startswith(settings.mcp_path.rstrip("/") + "/"):
            del paths[path]
        elif path not in FREE_PATHS and path not in PAID_PATHS:
            # Keep only L0 free + the three paid nowcast POSTs.
            del paths[path]

    _verbs = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    for path, methods in list(paths.items()):
        if not isinstance(methods, dict):
            continue
        if path in FREE_PATHS:
            for verb, op in methods.items():
                if verb.lower() in _verbs and isinstance(op, dict):
                    op["security"] = []
                    if path == "/v1/demo/sample" and verb.lower() == "get":
                        op["summary"] = "Fetch a synthetic unpaid nowcast sample fixture"
                        op["description"] = (
                            "Unpaid synthetic fixture for schema inspection only. "
                            "Not live PJM and not a nowcast."
                        )
            continue
        if path not in PAID_PATHS:
            continue
        post = methods.get("post")
        if not isinstance(post, dict):
            continue
        post["security"] = [{"x402": []}]
        post["summary"] = PAID_SUMMARIES[path]
        post["description"] = PAID_DESCRIPTIONS[path] + " " + DISCLAIMER
        post["x-payment-info"] = payment_info(settings, path)
        post["requestBody"] = {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{_REQUEST_MODELS[path].__name__}"},
                }
            },
        }
        responses = post.setdefault("responses", {})
        responses["200"] = {
            "description": "Descriptive statistics for the requested families.",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/NowcastEnvelope"}
                }
            },
        }
        responses["402"] = {"$ref": "#/components/responses/PaymentRequired"}
        responses["503"] = {"$ref": "#/components/responses/DataUnavailable"}
        if path != "/v1/nowcast/latest":
            responses["400"] = {
                "description": "Paid request with invalid window or body.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorBody"}
                    }
                },
            }

    schema["paths"] = paths
    return schema


def install_openapi(app: FastAPI, settings: Settings) -> None:
    def _openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        raw = get_openapi(
            title="pjm-nowcast",
            version=__version__,
            description=f"{WHAT_IT_IS} {DISCLAIMER}",
            routes=app.routes,
        )
        app.openapi_schema = customize_openapi(raw, settings)
        return app.openapi_schema

    app.openapi = _openapi  # type: ignore[method-assign]
