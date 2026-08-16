"""Paid route table. Prices are per path so the gate can run before body parse."""

from __future__ import annotations

from pjm_nowcast.settings import Settings

PAID_ROUTES: dict[str, str] = {
    "/v1/nowcast/latest": "l1",
    "/v1/nowcast/history": "l2",
    "/v1/nowcast/history/extended": "l3",
}

FREE_TIER_ELIGIBLE = {"/v1/nowcast/latest"}


def price_for(path: str, settings: Settings) -> str:
    tier = PAID_ROUTES.get(path)
    if tier == "l1":
        return settings.price_l1
    if tier == "l2":
        return settings.price_l2
    if tier == "l3":
        return settings.price_l3
    return "$0.00"


def match_paid_path(path: str) -> str | None:
    if path in PAID_ROUTES:
        return path
    # trailing slash
    stripped = path.rstrip("/") or "/"
    if stripped in PAID_ROUTES:
        return stripped
    return None
