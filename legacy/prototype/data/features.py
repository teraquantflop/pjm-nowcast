"""
Turn a raw scrape dict into a FeatureVector.
Maintains a short price history for a simple realized-vol estimate.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Deque, Optional

from model.state import FeatureVector

_price_history: Deque[float] = deque(maxlen=8)


def build_features(
    raw: dict,
    previous: Optional[FeatureVector],
) -> FeatureVector:
    ts: datetime = raw["ts"]
    load = float(raw["load_mw"])
    price = float(raw["rto_lmp"])
    quality = float(raw.get("quality", 1.0))

    if previous is not None and math.isfinite(previous.load_mw):
        load_ramp = load - previous.load_mw
    else:
        load_ramp = 0.0

    _price_history.append(price)
    if len(_price_history) >= 3:
        diffs = [
            _price_history[i] - _price_history[i - 1]
            for i in range(1, len(_price_history))
        ]
        price_vol = float(math.sqrt(sum(d * d for d in diffs) / len(diffs)))
    else:
        price_vol = 0.0

    hour_frac = ts.hour + ts.minute / 60.0
    angle = 2 * math.pi * hour_frac / 24.0
    hour_sin = math.sin(angle)
    hour_cos = math.cos(angle)
    is_weekend = 1 if ts.weekday() >= 5 else 0

    peak_today = raw.get("forecast_peak_today_mw")
    peak_tom = raw.get("forecast_peak_tomorrow_mw")
    if peak_today is not None:
        try:
            peak_today = float(peak_today)
        except (TypeError, ValueError):
            peak_today = None
    if peak_tom is not None:
        try:
            peak_tom = float(peak_tom)
        except (TypeError, ValueError):
            peak_tom = None

    zonals = raw.get("zonal_lmps") or {}
    if not isinstance(zonals, dict):
        zonals = {}
    zonals = {str(k).upper(): float(v) for k, v in zonals.items() if v is not None}

    return FeatureVector(
        ts=ts,
        load_mw=load,
        load_ramp=load_ramp,
        price=price,
        price_vol=price_vol,
        hour_sin=hour_sin,
        hour_cos=hour_cos,
        is_weekend=is_weekend,
        quality=quality,
        forecast_peak_today_mw=peak_today,
        forecast_peak_tomorrow_mw=peak_tom,
        zonal_lmps=zonals or None,
    )
