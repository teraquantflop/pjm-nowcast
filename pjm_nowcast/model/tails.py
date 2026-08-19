from __future__ import annotations

from typing import Dict

from pjm_nowcast.model.state import Snapshot


def residual_scales(snap: Snapshot) -> Dict[str, float]:
    names = ["load_mw", "load_ramp", "price", "price_vol", "hour_sin", "hour_cos"]
    if not snap.residual_abs_ewm:
        return {n: float("nan") for n in names}
    return {n: float(v) for n, v in zip(names, snap.residual_abs_ewm)}
