"""x402 Bazaar body-discovery blobs for paid nowcast routes.

``bazaar.schema`` validates ``info`` (PayAI / official SDK envelope).
Request-body JSON Schema lives at ``schema.properties.input.properties.body``.
"""

from __future__ import annotations

from typing import Any

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.payments.routes import PAID_ROUTES
from pjm_nowcast.spread_card import SPREAD_CARD_PATH, spread_card_bazaar_extension

ASOF_EXAMPLE = "2026-10-09T18:00:00-04:00"

_LATEST_IN: dict[str, Any] = {}
_HISTORY_IN: dict[str, Any] = {"windowHours": 24}
_EXTENDED_IN: dict[str, Any] = {"windowHours": 168}
_REGIME_IN: dict[str, Any] = {}
_SPREADS_IN: dict[str, Any] = {}
_ASOF_IN: dict[str, Any] = {"asOf": ASOF_EXAMPLE}
_SNAPSHOTS_IN: dict[str, Any] = {
    "from": "2026-10-09T00:00:00-04:00",
    "to": "2026-10-10T00:00:00-04:00",
}

_LATEST_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "stale": False,
    "price_vol": 2.5,
    "price_vol_missing": False,
    "rtoLmp": {"unit": "USD/MWh", "last": 41.0, "mean": 38.2},
    "zonalSpread": {
        "unit": "USD/MWh",
        "lastSpread": 5.1,
        "zones": {"BGE": 46.0},
    },
    "rtoLoad": {"unit": "MW", "last": 90000.0},
}

_HISTORY_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "windowHours": 24,
    "resolution": "native",
    "rtoLmp": {
        "unit": "USD/MWh",
        "n": 48,
        "last": 41.0,
        "points": [{"t": "2026-10-09T17:00:00-04:00", "value": 40.0}],
    },
}

_EXTENDED_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "windowHours": 168,
    "resolution": "native",
    "rtoLmp": {"unit": "USD/MWh", "n": 200, "last": 41.0},
}

_REGIME_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "entropy": 1.1,
    "posteriors": [0.1, 0.2, 0.1, 0.1, 0.5],
    "kStar": 4,
}

_SPREADS_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "unit": "USD/MWh",
    "lastSpread": 5.1,
    "lastP05": 41.0,
    "lastP95": 46.1,
    "zones": {"AECO": 42.0, "BGE": 46.0, "PEPCO": 44.0},
}

_ASOF_OUT: dict[str, Any] = {
    "asOf": ASOF_EXAMPLE,
    "ageSeconds": 120,
    "pinnedAsOf": ASOF_EXAMPLE,
    "rtoLmp": {"unit": "USD/MWh", "last": 41.0},
}

_SNAPSHOTS_OUT: dict[str, Any] = {
    "disclaimer": (
        DISCLAIMER
        + " Append-only snapshots of what /latest reported for that EPT hour-beginning. "
        "Not a forward forecast of a future hour. Hours without a row have no stored nowcast (null, not zero). "
        "Residuals are only defined where a snapshot exists."
    ),
    "windowDays": 90,
    "from": "2026-10-09T00:00:00-04:00",
    "to": "2026-10-10T00:00:00-04:00",
    "count": 1,
    "snapshots": [
        {
            "asof": "2026-10-09T18:05:00-04:00",
            "target_hour_ept": "2026-10-09T18:00:00-04:00",
            "rto_nc": 41.0,
            "spr_nc": 5.1,
            "zone_nc": {"BGE": 46.0},
        }
    ],
}

_EMPTY_OBJECT: dict[str, Any] = {"type": "object", "properties": {}}

_LATEST_IN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "families": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["rto_lmp", "zonal_spread", "rto_load"],
            },
        }
    },
}

_HISTORY_IN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "windowHours": {
            "type": "integer",
            "minimum": 1,
            "maximum": 72,
            "description": "Trailing window in hours. Default 24. L2 max 72.",
        },
        "families": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["rto_lmp", "zonal_spread", "rto_load"],
            },
        },
    },
}

_EXTENDED_IN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "windowHours": {
            "type": "integer",
            "minimum": 1,
            "description": "Trailing window in hours. Default 168, capped by retention.",
        },
        "families": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["rto_lmp", "zonal_spread", "rto_load"],
            },
        },
        "resolution": {"type": "string", "enum": ["native", "hourly"]},
        "compare": {"type": "string", "enum": ["none", "prior_period"]},
    },
}

_ASOF_IN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "asOf": {
            "type": "string",
            "description": "ISO-8601 observation clock with offset. Required. No interpolation.",
        }
    },
    "required": ["asOf"],
}

_SNAPSHOTS_IN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "from": {
            "type": "string",
            "description": "ISO-8601 start with offset (inclusive). Capped at 90-day lookback.",
        },
        "to": {
            "type": "string",
            "description": "ISO-8601 end with offset (exclusive).",
        },
    },
    "required": ["from", "to"],
}

_ENVELOPE_PROPS: dict[str, Any] = {
    "asOf": {"type": "string"},
    "ageSeconds": {"type": "integer"},
    "stale": {"type": "boolean"},
}

_LATEST_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Descriptive snapshot of the last scrape. Not a forecast.",
    "properties": {
        **_ENVELOPE_PROPS,
        "price_vol": {"type": ["number", "null"]},
        "price_vol_missing": {"type": "boolean"},
        "rtoLmp": {"type": "object"},
        "zonalSpread": {"type": "object"},
        "rtoLoad": {"type": "object"},
    },
}

_HISTORY_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Trailing descriptive history. Not a forecast.",
    "properties": {
        **_ENVELOPE_PROPS,
        "windowHours": {"type": "integer"},
        "resolution": {"type": "string"},
        "rtoLmp": {"type": "object"},
        "zonalSpread": {"type": "object"},
        "rtoLoad": {"type": "object"},
    },
}

_REGIME_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "HMM regime snapshot. Descriptive only. Not a forecast.",
    "properties": {
        **_ENVELOPE_PROPS,
        "entropy": {"type": ["number", "null"]},
        "posteriors": {"type": "array", "items": {"type": "number"}},
        "kStar": {"type": ["integer", "null"]},
    },
}

_SPREADS_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Zone-level LMP spread table for the latest print. No history dump.",
    "properties": {
        **_ENVELOPE_PROPS,
        "unit": {"type": "string"},
        "lastSpread": {"type": ["number", "null"]},
        "lastP05": {"type": ["number", "null"]},
        "lastP95": {"type": ["number", "null"]},
        "zones": {"type": "object"},
    },
}

_ASOF_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Descriptive snapshot pinned to asOf. Not a forecast.",
    "properties": {
        **_ENVELOPE_PROPS,
        "pinnedAsOf": {"type": "string"},
        "rtoLmp": {"type": "object"},
        "zonalSpread": {"type": "object"},
        "rtoLoad": {"type": "object"},
    },
}

_SNAPSHOTS_OUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Append-only /latest snapshots by EPT hour-beginning. "
        "Not a forward forecast. Pre-store hours have no row."
    ),
    "properties": {
        "disclaimer": {"type": "string"},
        "windowDays": {"type": "integer"},
        "from": {"type": "string"},
        "to": {"type": ["string", "null"]},
        "count": {"type": "integer"},
        "snapshots": {"type": "array", "items": {"type": "object"}},
    },
}


def declare_http_json_discovery(
    *,
    body: dict[str, Any],
    input_schema: dict[str, Any],
    example: dict[str, Any],
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """PayAI/x402 v2 bazaar blob for a JSON POST.

    Same envelope as ``declare_discovery_extension`` (info + schema that
    validates info; request body at ``schema.properties.input.properties.body``).
    ``method`` is set to POST here because unpaid probes use the local 402 stub
    and never run ``bazaar_resource_server_extension`` enrichment.

    Implemented locally: ``from x402.extensions.bazaar`` requires the optional
    ``jsonschema`` extra, which this service does not install.
    """
    ext = _official_declare(
        body=body,
        input_schema=input_schema,
        example=example,
        output_schema=output_schema,
    )
    if ext is not None:
        info = (ext.get("bazaar") or {}).get("info") or {}
        inp = info.get("input")
        if isinstance(inp, dict):
            inp["method"] = "POST"
        return ext
    return _envelope(
        body=body,
        input_schema=input_schema,
        example=example,
        output_schema=output_schema,
    )


def _official_declare(
    *,
    body: dict[str, Any],
    input_schema: dict[str, Any],
    example: dict[str, Any],
    output_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Use the SDK helper when the extensions extra is installed."""
    try:
        from x402.extensions.bazaar.resource_service import (
            OutputConfig,
            declare_discovery_extension,
        )
    except Exception:
        return None
    return declare_discovery_extension(
        input=body,
        input_schema=input_schema,
        body_type="json",
        output=OutputConfig(example=example, schema=output_schema),
    )


def _envelope(
    *,
    body: dict[str, Any],
    input_schema: dict[str, Any],
    example: dict[str, Any],
    output_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Mirror x402.extensions.bazaar.resource_service body discovery."""
    schema_properties: dict[str, Any] = {
        "input": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "const": "http"},
                "method": {"type": "string", "enum": ["POST", "PUT", "PATCH"]},
                "bodyType": {
                    "type": "string",
                    "enum": ["json", "form-data", "text"],
                },
                "body": input_schema,
            },
            "required": ["type", "method", "bodyType", "body"],
            "additionalProperties": False,
        }
    }
    if example is not None:
        example_field: dict[str, Any] = {"type": "object"}
        if output_schema:
            example_field.update(output_schema)
        schema_properties["output"] = {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "example": example_field,
            },
            "required": ["type"],
        }
    return {
        "bazaar": {
            "info": {
                "input": {
                    "type": "http",
                    "method": "POST",
                    "bodyType": "json",
                    "body": body if body else {},
                },
                "output": {"type": "json", "example": example},
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": schema_properties,
                "required": ["input"],
            },
        }
    }


def _declare(
    *,
    body: dict[str, Any],
    input_schema: dict[str, Any],
    example: dict[str, Any],
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    return declare_http_json_discovery(
        body=body,
        input_schema=input_schema,
        example=example,
        output_schema=output_schema,
    )


_NOWCAST: dict[str, dict[str, Any]] = {
    "/v1/nowcast/latest": {
        "body": _LATEST_IN,
        "input_schema": _LATEST_IN_SCHEMA,
        "example": _LATEST_OUT,
        "output_schema": _LATEST_OUT_SCHEMA,
    },
    "/v1/nowcast/history": {
        "body": _HISTORY_IN,
        "input_schema": _HISTORY_IN_SCHEMA,
        "example": _HISTORY_OUT,
        "output_schema": _HISTORY_OUT_SCHEMA,
    },
    "/v1/nowcast/history/extended": {
        "body": _EXTENDED_IN,
        "input_schema": _EXTENDED_IN_SCHEMA,
        "example": _EXTENDED_OUT,
        "output_schema": _HISTORY_OUT_SCHEMA,
    },
    "/v1/nowcast/regime": {
        "body": _REGIME_IN,
        "input_schema": _EMPTY_OBJECT,
        "example": _REGIME_OUT,
        "output_schema": _REGIME_OUT_SCHEMA,
    },
    "/v1/nowcast/spreads": {
        "body": _SPREADS_IN,
        "input_schema": _EMPTY_OBJECT,
        "example": _SPREADS_OUT,
        "output_schema": _SPREADS_OUT_SCHEMA,
    },
    "/v1/nowcast/asof": {
        "body": _ASOF_IN,
        "input_schema": _ASOF_IN_SCHEMA,
        "example": _ASOF_OUT,
        "output_schema": _ASOF_OUT_SCHEMA,
    },
    "/v1/nowcast/snapshots": {
        "body": _SNAPSHOTS_IN,
        "input_schema": _SNAPSHOTS_IN_SCHEMA,
        "example": _SNAPSHOTS_OUT,
        "output_schema": _SNAPSHOTS_OUT_SCHEMA,
    },
}


def bazaar_extension_for(path: str) -> dict[str, Any] | None:
    """Bazaar blob for a paid path, or None if the path is not paid."""
    if path == SPREAD_CARD_PATH:
        return spread_card_bazaar_extension()
    spec = _NOWCAST.get(path)
    if spec is None:
        return None
    return _declare(**spec)


def paid_nowcast_bazaar_paths() -> tuple[str, ...]:
    return tuple(p for p in PAID_ROUTES if p != SPREAD_CARD_PATH)
