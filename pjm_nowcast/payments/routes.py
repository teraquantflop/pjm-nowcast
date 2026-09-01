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

SOLANA_NETWORK = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
POLYGON_NETWORK = "eip155:137"
# Native Circle USDC on Polygon PoS (not bridged USDC.e).
POLYGON_USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
POLYGON_USDC_EIP712_EXTRA = {"name": "USD Coin", "version": "2"}


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


def pay_to_by_network(settings: Settings) -> dict[str, str]:
    """Receive addresses keyed by CAIP-2. Internal / header challenge only."""
    nets = set(settings.network_list)
    out: dict[str, str] = {}
    if settings.svm_pay_to and SOLANA_NETWORK in nets:
        out[SOLANA_NETWORK] = settings.svm_pay_to
    if settings.evm_pay_to and BASE_NETWORK in nets:
        out[BASE_NETWORK] = settings.evm_pay_to
    if settings.poly_pay_to and POLYGON_NETWORK in nets:
        out[POLYGON_NETWORK] = settings.poly_pay_to
    return out


def public_network_names(settings: Settings) -> list[str]:
    """Short names for free catalogs. Never CAIP genesis hashes or addresses."""
    names: list[str] = []
    for n in settings.network_list:
        if n == SOLANA_NETWORK or n.startswith("solana:"):
            label = "solana"
        elif n == BASE_NETWORK:
            label = "base"
        elif n == POLYGON_NETWORK:
            label = "polygon"
        else:
            continue
        if label not in names:
            names.append(label)
    return names


def payment_configured(settings: Settings) -> bool:
    return bool(pay_to_by_network(settings))
