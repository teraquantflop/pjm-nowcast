"""Pure trailing descriptive statistics. No I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear interpolation percentile. p in [0, 100]."""
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not xs:
        return None
    xs.sort()
    if len(xs) == 1:
        return xs[0]
    rank = (p / 100.0) * (len(xs) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs[lo]
    w = rank - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def sample_std(values: Sequence[float]) -> float | None:
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


@dataclass(frozen=True)
class Summary:
    n: int
    last: float | None
    min: float | None
    max: float | None
    mean: float | None
    std: float | None
    p05: float | None
    p50: float | None
    p95: float | None

    def as_public(self, unit: str) -> dict:
        return {
            "unit": unit,
            "n": self.n,
            "last": self.last,
            "min": self.min,
            "max": self.max,
            "mean": self.mean,
            "std": self.std,
            "p05": self.p05,
            "p50": self.p50,
            "p95": self.p95,
        }


def summarize(values: Sequence[float | None]) -> Summary:
    xs = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not xs:
        return Summary(
            n=0,
            last=None,
            min=None,
            max=None,
            mean=None,
            std=None,
            p05=None,
            p50=None,
            p95=None,
        )
    return Summary(
        n=len(xs),
        last=xs[-1],
        min=min(xs),
        max=max(xs),
        mean=sum(xs) / len(xs),
        std=sample_std(xs),
        p05=percentile(xs, 5),
        p50=percentile(xs, 50),
        p95=percentile(xs, 95),
    )


def spread_of(zonals: dict[str, float], min_zones: int) -> tuple[float | None, float | None, float | None]:
    vals = [float(v) for v in zonals.values() if v is not None and math.isfinite(float(v))]
    if len(vals) < min_zones:
        return None, None, None
    p05 = percentile(vals, 5)
    p95 = percentile(vals, 95)
    if p05 is None or p95 is None:
        return None, None, None
    return p05, p95, p95 - p05
