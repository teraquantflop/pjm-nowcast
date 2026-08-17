"""Paid route table. Prices are per path so the gate can run before body parse."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from pjm_nowcast.settings import Settings

PAID_ROUTES: dict[str, str] = {
    "/v1/nowcast/latest": "l1",
    "/v1/nowcast/history": "l2",
    "/v1/nowcast/history/extended": "l3",
}

FREE_TIER_ELIGIBLE = {"/v1/nowcast/latest"}

PAID_DESCRIPTIONS: dict[str, str] = {
    "/v1/nowcast/latest": (
        "Latest descriptive snapshot of RTO LMP, zonal spreads, and RTO load."
    ),
    "/v1/nowcast/history": (
        "1–72h descriptive history of RTO LMP, zonal spreads, and RTO load."
    ),
    "/v1/nowcast/history/extended": (
        "Extended descriptive history within the retention window."
    ),
}

# USDC has 6 decimals. Dollar prices are unchanged; these are the atomic strings
# scanners need: $0.02 → "20000", $0.10 → "100000", $0.25 → "250000".
USDC_DECIMALS = 6
CHALLENGE_TIMEOUT_SECONDS = 60

# Base mainnet USDC (EIP-3009). Required by @x402/evm EIP-712 domain params.
BASE_USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_USDC_EIP712_EXTRA = {"name": "USD Coin", "version": "2"}
BASE_NETWORK = "eip155:8453"


def resource_url(settings: Settings, path: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}{path}"


def resource_object(settings: Settings, path: str) -> dict[str, str]:
    out = {"url": resource_url(settings, path)}
    desc = PAID_DESCRIPTIONS.get(path)
    if desc:
        out["description"] = desc
    return out


def price_for(path: str, settings: Settings) -> str:
    tier = PAID_ROUTES.get(path)
    if tier == "l1":
        return settings.price_l1
    if tier == "l2":
        return settings.price_l2
    if tier == "l3":
        return settings.price_l3
    return "$0.00"


def usdc_atomic_amount(price: str) -> str:
    """Convert a dollar price like '$0.02' to a USDC atomic-unit string."""
    raw = (price or "").strip()
    if raw.startswith("$"):
        raw = raw[1:]
    dollars = Decimal(raw or "0")
    quant = Decimal(10) ** USDC_DECIMALS
    atomic = (dollars * quant).to_integral_value(rounding=ROUND_HALF_UP)
    return str(int(atomic))


def match_paid_path(path: str) -> str | None:
    if path in PAID_ROUTES:
        return path
    # trailing slash
    stripped = path.rstrip("/") or "/"
    if stripped in PAID_ROUTES:
        return stripped
    return None
