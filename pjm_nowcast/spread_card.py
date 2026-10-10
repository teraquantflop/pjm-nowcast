"""Shared copy and path for POST /v1/spread/probability-card.

Same words on every discovery surface. Not a forecast.
"""

from __future__ import annotations

from typing import Any

SPREAD_CARD_PATH = "/v1/spread/probability-card"
SPREAD_CARD_MCP_TOOL = "spread_probability_card"

SPREAD_CARD_TITLE = "PJM zonal spread jump probability"
SPREAD_CARD_PRODUCT = "empirical probability card"
SPREAD_CARD_BAR = "evening congestion bar"

SPREAD_CARD_WHEN_TO_USE = (
    "next on-peak day or trailing congestion-season check"
)
SPREAD_CARD_WHEN_NOT_TO_USE = (
    "month-ahead, season-ahead, Black vol, a price forecast"
)

SPREAD_CARD_BUYER_BEWARE = (
    "empirical hit rate on a named sample, not a forecast, not a mid, "
    "not for month-ahead or season-ahead. Nowcast is an input. Fair value "
    "with a caller-supplied vol belongs on the derivatives pricer."
)

SPREAD_CARD_RELATED = (
    "https://derivatives-pricer-production.up.railway.app"
)
SPREAD_CARD_RELATED_NOTE = (
    "European pricing if the caller already has vol"
)

SPREAD_CARD_EXAMPLE_REQUEST: dict[str, Any] = {"lookbackDays": 5}

SPREAD_CARD_EXAMPLE_CARD: dict[str, Any] = {
    "sample": {"tag": "high-congestion-season", "dayCount": 5},
    "K": 12.4,
    "hitRate": 0.4,
    "avgPayoff": 1.8,
}

SAMPLE_TAG = "high-congestion-season"

LOOKBACK_DEFAULT = 5
LOOKBACK_MAX = 30
MIN_PAIRED_DAYS = 3


def spread_card_description() -> str:
    return (
        f"{SPREAD_CARD_TITLE}. {SPREAD_CARD_PRODUCT} for the {SPREAD_CARD_BAR}. "
        f"whenToUse: {SPREAD_CARD_WHEN_TO_USE}. "
        f"whenNotToUse: {SPREAD_CARD_WHEN_NOT_TO_USE}. "
        f"Related resource: {SPREAD_CARD_RELATED} — {SPREAD_CARD_RELATED_NOTE}."
    )


def spread_card_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "lookbackDays": {
                "type": "integer",
                "minimum": 1,
                "maximum": LOOKBACK_MAX,
                "default": LOOKBACK_DEFAULT,
                "description": (
                    f"Trailing EPT calendar days. Default {LOOKBACK_DEFAULT}, "
                    f"max {LOOKBACK_MAX}."
                ),
            },
            "asOf": {
                "type": "string",
                "description": "Optional ISO-8601 sample end. Default: now.",
            },
        },
        "additionalProperties": False,
    }


def spread_card_bazaar_extension() -> dict[str, Any]:
    """x402 Bazaar body-discovery blob for this route only."""
    try:
        from x402.extensions.bazaar import OutputConfig, declare_discovery_extension

        return declare_discovery_extension(
            input=SPREAD_CARD_EXAMPLE_REQUEST,
            input_schema=spread_card_input_schema(),
            body_type="json",
            output=OutputConfig(
                example=SPREAD_CARD_EXAMPLE_CARD,
                schema=spread_card_output_schema(),
            ),
        )
    except Exception:
        return {
            "bazaar": {
                "info": {
                    "input": {
                        "type": "http",
                        "bodyType": "json",
                        "body": SPREAD_CARD_EXAMPLE_REQUEST,
                    },
                    "output": {
                        "type": "json",
                        "example": SPREAD_CARD_EXAMPLE_CARD,
                    },
                },
                "schema": {
                    "type": "object",
                    "required": ["input"],
                    "properties": {
                        "input": {"type": "object"},
                        "output": {"type": "object"},
                    },
                },
            }
        }


def spread_card_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            f"{SPREAD_CARD_PRODUCT}. Empirical only. Not a forecast, not a mid."
        ),
        "properties": {
            "K": {"type": "number"},
            "hitDays": {"type": "integer"},
            "hitRate": {"type": "number"},
            "avgPayoff": {"type": "number"},
            "dailyMaxP50": {"type": "number"},
            "dailyMaxP95": {"type": "number"},
            "sample": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "const": SAMPLE_TAG},
                    "dayCount": {"type": "integer"},
                    "firstEptDate": {"type": "string"},
                    "lastEptDate": {"type": "string"},
                },
            },
            "latestCompleteDay": {"type": "object"},
            "latestNowcast": {"type": "object"},
            "buyerBeware": {"type": "string"},
        },
        "example": SPREAD_CARD_EXAMPLE_CARD,
    }
