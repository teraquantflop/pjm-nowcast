"""Rolling realized LMP dollar vol: RMS of successive diffs.

Same formula as the poller feature window. Not trailing mix std, not Black vol.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

PRICE_VOL_WINDOW = 8
PRICE_VOL_MIN_PRINTS = 3


def finite_lmps(
    values: Sequence[object],
    *,
    limit: int = PRICE_VOL_WINDOW,
) -> list[float]:
    out: list[float] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            out.append(parsed)
    if limit is not None and len(out) > limit:
        return out[-limit:]
    return out


def rms_price_vol(prices: Sequence[float]) -> float | None:
    """RMS of successive diffs over the last up-to-8 prints.

    Returns None when there are fewer than 3 finite prints, or the RMS is
    non-finite / <= 0 (flat tape is treated as missing, matching the poller).
    """
    xs = finite_lmps(prices, limit=PRICE_VOL_WINDOW)
    if len(xs) < PRICE_VOL_MIN_PRINTS:
        return None
    diffs = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
    vol = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    if not math.isfinite(vol) or vol <= 0.0:
        return None
    return float(vol)


def price_vol_from_lmps(values: Sequence[object]) -> tuple[float | None, bool]:
    vol = rms_price_vol(values)
    if vol is None:
        return None, True
    return vol, False
