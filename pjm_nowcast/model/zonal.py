"""Zonal percentile spread and high-spread flag (internal)."""

from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

from pjm_nowcast.model.params import (
    EWM_ALPHA,
    EWM_ALPHA_WARM,
    SPREAD_ABS_USD_DEFAULT,
    SPREAD_K_DEFAULT,
    WARM_OBS,
)
from pjm_nowcast.model.state import FeatureVector, Snapshot

log = logging.getLogger("pjm_nowcast.model.zonal")


def _spread_knobs() -> tuple[float, float, int]:
    try:
        from pjm_nowcast.settings import get_settings

        s = get_settings()
        return (
            float(s.spread_abs_usd),
            float(s.spread_k),
            int(s.min_zones_for_spread),
        )
    except Exception:
        return SPREAD_ABS_USD_DEFAULT, SPREAD_K_DEFAULT, 4


def empirical_percentile(values: List[float], p: float) -> float:
    if not values:
        return float("nan")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    w = rank - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def zonal_percentiles(
    zonal_lmps: Optional[Dict[str, float]],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not zonal_lmps:
        return None, None, None
    _abs, _k, min_zones = _spread_knobs()
    vals = [
        float(v)
        for v in zonal_lmps.values()
        if v is not None and math.isfinite(float(v))
    ]
    if len(vals) < min_zones:
        return None, None, None
    p05 = empirical_percentile(vals, 5)
    p95 = empirical_percentile(vals, 95)
    return p05, p95, p95 - p05


def update_zonal_and_peak(snap: Snapshot, feats: FeatureVector) -> Snapshot:
    from zoneinfo import ZoneInfo

    alpha = EWM_ALPHA_WARM if snap.n_obs < WARM_OBS else EWM_ALPHA
    ET = ZoneInfo("America/New_York")
    abs_thresh, spread_k, _min_z = _spread_knobs()

    if feats.forecast_peak_today_mw is not None:
        snap.forecast_peak_today_mw = feats.forecast_peak_today_mw
    if feats.forecast_peak_tomorrow_mw is not None:
        snap.forecast_peak_tomorrow_mw = feats.forecast_peak_tomorrow_mw

    p05, p95, spread = zonal_percentiles(feats.zonal_lmps)
    if spread is None:
        return snap

    snap.zonal_p05 = p05
    snap.zonal_p95 = p95
    snap.zonal_spread = spread

    if snap.zonal_spread_mean is None:
        snap.zonal_spread_mean = spread
        snap.zonal_spread_var = 0.0
        snap.zonal_spread_ewm_abs_resid = 0.0
    else:
        old_m = snap.zonal_spread_mean
        new_m = (1 - alpha) * old_m + alpha * spread
        resid = spread - new_m
        snap.zonal_spread_var = (1 - alpha) * (snap.zonal_spread_var or 0.0) + alpha * resid * resid
        snap.zonal_spread_ewm_abs_resid = (
            (1 - alpha) * (snap.zonal_spread_ewm_abs_resid or 0.0) + alpha * abs(resid)
        )
        snap.zonal_spread_mean = new_m

    sigma = math.sqrt(max(snap.zonal_spread_var or 0.0, 1e-8))
    ewm_thresh = (snap.zonal_spread_mean or 0.0) + spread_k * sigma
    high = spread >= abs_thresh or spread > ewm_thresh
    snap.last_high_spread = high
    log.info(
        "high_spread=%s  spread=%.2f  abs_thresh=%.2f  ewm_thresh=%.2f",
        high,
        spread,
        abs_thresh,
        ewm_thresh,
    )

    day = feats.ts.astimezone(ET).date().isoformat()
    if snap.spread_day != day:
        snap.spread_day = day
        snap.spread_max_today = spread
        snap.spread_min_today = spread
        snap.spread_high_count_today = 1 if high else 0
        snap.spread_n_today = 1
    else:
        snap.spread_n_today = int(snap.spread_n_today or 0) + 1
        if snap.spread_max_today is None or spread > snap.spread_max_today:
            snap.spread_max_today = spread
        if snap.spread_min_today is None or spread < snap.spread_min_today:
            snap.spread_min_today = spread
        if high:
            snap.spread_high_count_today = int(snap.spread_high_count_today or 0) + 1

    price_resid = 0.0
    if snap.residual_abs_ewm and len(snap.residual_abs_ewm) > 2:
        price_resid = float(snap.residual_abs_ewm[2])
    if not math.isfinite(price_resid):
        return snap

    if high:
        if snap.cond_price_resid_high_spread is None:
            snap.cond_price_resid_high_spread = price_resid
        else:
            snap.cond_price_resid_high_spread = (
                (1 - alpha) * snap.cond_price_resid_high_spread + alpha * price_resid
            )
    else:
        if snap.cond_price_resid_low_spread is None:
            snap.cond_price_resid_low_spread = price_resid
        else:
            snap.cond_price_resid_low_spread = (
                (1 - alpha) * snap.cond_price_resid_low_spread + alpha * price_resid
            )
    return snap
