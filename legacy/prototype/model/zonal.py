"""
Zonal percentile spread, peak headroom, mild-sine curve proxy,
and conditional residual scales by spread regime.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from config import (
    EWM_ALPHA,
    EWM_ALPHA_WARM,
    MIN_ZONES_FOR_SPREAD,
    PEAK_HOUR_EPT,
    SPREAD_K,
    WARM_OBS,
)
from .state import FeatureVector, Snapshot


def empirical_percentile(values: List[float], p: float) -> float:
    """Nearest-rank style percentile; p in [0, 100]."""
    if not values:
        return float("nan")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    # linear interpolation between ranks
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    w = rank - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def zonal_percentiles(zonal_lmps: Optional[Dict[str, float]]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not zonal_lmps:
        return None, None, None
    vals = [float(v) for v in zonal_lmps.values() if v is not None and math.isfinite(float(v))]
    if len(vals) < MIN_ZONES_FOR_SPREAD:
        return None, None, None
    p05 = empirical_percentile(vals, 5)
    p95 = empirical_percentile(vals, 95)
    return p05, p95, p95 - p05


def update_zonal_and_peak(snap: Snapshot, feats: FeatureVector) -> Snapshot:
    """
    Update zonal spread EWMs, high_spread flag, conditional price residual
    scales, official peaks, and intraday spread trajectory.
    Does not change HMM core arrays.
    """
    from zoneinfo import ZoneInfo

    alpha = EWM_ALPHA_WARM if snap.n_obs < WARM_OBS else EWM_ALPHA
    ET = ZoneInfo("America/New_York")

    # peaks (last seen)
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

    # EWM of spread level + variance
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
    high = spread > (snap.zonal_spread_mean or 0.0) + SPREAD_K * sigma
    snap.last_high_spread = high

    # --- intraday spread trajectory (reset on Eastern date change) ---
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

    # conditional price residual scale (scaled-space residual for price dim index 2)
    price_resid = 0.0
    if snap.residual_abs_ewm and len(snap.residual_abs_ewm) > 2:
        price_resid = float(snap.residual_abs_ewm[2])

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


def headroom_mw(snap: Snapshot, load_mw: float) -> Optional[float]:
    if snap.forecast_peak_today_mw is None:
        return None
    return snap.forecast_peak_today_mw - load_mw


def mild_sine_peak_proxy(
    load_mw: float,
    forecast_peak_today_mw: Optional[float],
    hour_frac_ept: float,
    peak_hour: float = PEAK_HOUR_EPT,
) -> Optional[float]:
    """
    Crude intraday path toward official peak using a mild raised-sine
    from now until peak_hour. After peak_hour, returns forecast peak as ceiling.
    Not PJM's official hourly forecast — proxy only.
    """
    if forecast_peak_today_mw is None or not math.isfinite(forecast_peak_today_mw):
        return None
    if hour_frac_ept >= peak_hour:
        return forecast_peak_today_mw

    # progress in [0, 1] from current hour to peak hour (same day)
    span = max(peak_hour - hour_frac_ept, 1e-3)
    # we don't know load at start of window; treat current as start of remaining path
    # proxy target at peak hour = forecast peak
    # mild sine: y = start + (end-start) * (1 - cos(pi * t)) / 2
    # here we report the implied end (peak), and optionally a "now-to-peak" guide value
    # return the official peak as the path endpoint; caller can show headroom
    return forecast_peak_today_mw


def predictor_bands(mean: float, std: float) -> Dict[str, float]:
    """Gaussian-ish N-sigma and ~95th from mixture moments."""
    std = max(std, 0.0)
    return {
        "mu": mean,
        "p1": mean + 1.0 * std,
        "p2": mean + 2.0 * std,
        "p3": mean + 3.0 * std,
        "p95": mean + 1.65 * std,
        "m1": mean - 1.0 * std,
        "m2": mean - 2.0 * std,
    }
