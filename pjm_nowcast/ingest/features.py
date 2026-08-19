"""Turn a scrape/normalize dict into a FeatureVector.

price_vol is rolling realized LMP std in $/MWh (RMS of successive diffs
over a short window). Not annualized Black vol.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Deque, Optional

from pjm_nowcast.model.state import FeatureVector

_price_history: Deque[float] = deque(maxlen=8)


def _f(v) -> float:
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def build_features(
    raw: dict,
    previous: Optional[FeatureVector],
) -> FeatureVector:
    ts: datetime = raw["ts"]
    load = _f(raw.get("load_mw"))
    price = _f(raw.get("rto_lmp") if raw.get("rto_lmp") is not None else raw.get("price"))
    quality = float(raw.get("quality", 1.0) or 1.0)

    if previous is not None and math.isfinite(previous.load_mw) and math.isfinite(load):
        load_ramp = load - previous.load_mw
    else:
        load_ramp = 0.0

    if math.isfinite(price):
        _price_history.append(price)
    if len(_price_history) >= 3:
        diffs = [
            _price_history[i] - _price_history[i - 1]
            for i in range(1, len(_price_history))
        ]
        price_vol = float(math.sqrt(sum(d * d for d in diffs) / len(diffs)))
    else:
        price_vol = 0.0

    price_vol_missing = (not math.isfinite(price_vol)) or price_vol <= 0.0
    if price_vol_missing:
        prev_vol = previous.price_vol if previous is not None else None
        if prev_vol is not None and math.isfinite(prev_vol) and prev_vol > 0.0:
            price_vol = float(prev_vol)

    hour_frac = ts.hour + ts.minute / 60.0
    angle = 2 * math.pi * hour_frac / 24.0
    hour_sin = math.sin(angle)
    hour_cos = math.cos(angle)
    is_weekend = 1 if ts.weekday() >= 5 else 0

    peak_today = raw.get("published_peak_today_mw", raw.get("forecast_peak_today_mw"))
    peak_tom = raw.get("published_peak_tomorrow_mw", raw.get("forecast_peak_tomorrow_mw"))
    try:
        peak_today = float(peak_today) if peak_today is not None else None
    except (TypeError, ValueError):
        peak_today = None
    try:
        peak_tom = float(peak_tom) if peak_tom is not None else None
    except (TypeError, ValueError):
        peak_tom = None

    zonals = raw.get("zonal_lmps") or raw.get("zonals") or {}
    if not isinstance(zonals, dict):
        zonals = {}
    clean = {}
    for k, v in zonals.items():
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            clean[str(k).upper()] = fv

    return FeatureVector(
        ts=ts,
        load_mw=load,
        load_ramp=load_ramp,
        price=price,
        price_vol=price_vol,
        price_vol_missing=price_vol_missing,
        hour_sin=hour_sin,
        hour_cos=hour_cos,
        is_weekend=is_weekend,
        quality=quality,
        forecast_peak_today_mw=peak_today,
        forecast_peak_tomorrow_mw=peak_tom,
        zonal_lmps=clean or None,
    )
