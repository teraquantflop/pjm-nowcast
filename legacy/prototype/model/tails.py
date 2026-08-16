"""
Very light tail / residual helpers.
In v0.1 we only track exponentially-weighted absolute residuals
so you can watch scale grow or shrink as the model learns.
Later we can replace this with proper quantile or EVT trackers.
"""

from __future__ import annotations

from typing import Dict

from .state import Snapshot


def residual_scales(snap: Snapshot) -> Dict[str, float]:
    names = ["load_mw", "load_ramp", "price", "price_vol", "hour_sin", "hour_cos"]
    if not snap.residual_abs_ewm:
        return {n: float("nan") for n in names}
    return {n: float(v) for n, v in zip(names, snap.residual_abs_ewm)}
