"""Snapshot history ring. PNG histograms are not generated."""

from __future__ import annotations

import math
from typing import Any, Dict
from zoneinfo import ZoneInfo

from pjm_nowcast.model.params import HISTORY_MAX
from pjm_nowcast.model.state import FeatureVector, Snapshot

ET = ZoneInfo("America/New_York")


def append_history(snap: Snapshot, feats: FeatureVector) -> None:
    if snap.history is None:
        snap.history = []
    load = float(feats.load_mw)
    price = float(feats.price)
    load_ok = math.isfinite(load)
    price_ok = math.isfinite(price)
    if not load_ok and not price_ok:
        return
    entry: Dict[str, Any] = {
        "ts": feats.ts.isoformat()
        if feats.ts.tzinfo
        else feats.ts.replace(tzinfo=ET).isoformat(),
    }
    if load_ok:
        entry["load_mw"] = load
    if price_ok:
        entry["price"] = price
    if snap.zonal_spread is not None and math.isfinite(float(snap.zonal_spread)):
        entry["zonal_spread"] = float(snap.zonal_spread)
    if snap.last_high_spread:
        entry["high_spread"] = True
    snap.history.append(entry)
    if len(snap.history) > HISTORY_MAX:
        snap.history = snap.history[-HISTORY_MAX:]
