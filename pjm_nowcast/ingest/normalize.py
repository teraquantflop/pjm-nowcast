"""Turn a raw fetch dict into store fields."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _finite(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def normalize(raw: dict[str, Any], previous_load: float | None) -> dict[str, Any]:
    load = _finite(raw.get("load_mw"))
    price = _finite(raw.get("rto_lmp"))
    ramp = None
    if load is not None and previous_load is not None:
        ramp = load - previous_load

    ts = raw.get("ts") or datetime.now(ET)
    fetched = raw.get("fetched_at") or datetime.now(ET)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if isinstance(fetched, str):
        fetched = datetime.fromisoformat(fetched)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ET)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=ET)

    zonals = raw.get("zonal_lmps") or {}
    clean_z: dict[str, float] = {}
    if isinstance(zonals, dict):
        for k, v in zonals.items():
            fv = _finite(v)
            if fv is not None:
                clean_z[str(k).upper()] = fv

    return {
        "ts": ts,
        "fetched_at": fetched,
        "load_mw": load,
        "rto_lmp": price,
        "published_peak_today_mw": _finite(raw.get("published_peak_today_mw")),
        "published_peak_tomorrow_mw": _finite(raw.get("published_peak_tomorrow_mw")),
        "quality": float(raw.get("quality", 1.0)),
        "source": str(raw.get("source", "unknown")),
        "as_of_text": raw.get("as_of_text"),
        "load_ramp_mw": ramp,
        "zonals": clean_z,
    }
