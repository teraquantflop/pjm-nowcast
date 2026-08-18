"""Turn stored observations into public response dicts."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.db.store import Observation, Store
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.descriptive import spread_of, summarize

Family = Literal["rto_lmp", "zonal_spread", "rto_load"]
ALL_FAMILIES: tuple[Family, ...] = ("rto_lmp", "zonal_spread", "rto_load")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def envelope(
    latest: Observation,
    n: int,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    age = max(0, int((now - latest.fetched_at).total_seconds()))
    return {
        "product": "pjm-nowcast",
        "disclaimer": DISCLAIMER,
        "timezone": "America/New_York",
        "asOf": latest.ts.isoformat(),
        "polledAt": latest.fetched_at.isoformat(),
        "ageSeconds": age,
        "maxAgeSeconds": settings.stale_after_seconds,
        "stale": age > settings.stale_after_seconds,
        "observationCount": n,
    }


def _lmp_block(obs: list[Observation]) -> dict[str, Any]:
    summary = summarize([o.rto_lmp for o in obs])
    return summary.as_public("USD/MWh")


def _load_block(obs: list[Observation], last: Observation) -> dict[str, Any]:
    summary = summarize([o.load_mw for o in obs])
    body = summary.as_public("MW")
    peak_today = last.published_peak_today_mw
    peak_tom = last.published_peak_tomorrow_mw
    last_load = last.load_mw
    vs = None
    if peak_today is not None and last_load is not None:
        vs = peak_today - last_load
    body["sourcePublishedPeakTodayMw"] = peak_today
    body["sourcePublishedPeakTomorrowMw"] = peak_tom
    body["vsPublishedPeakTodayMw"] = vs
    return body


def _spread_block(obs: list[Observation], last: Observation, min_zones: int) -> dict[str, Any]:
    spreads: list[float | None] = []
    last_p05 = last_p95 = last_spread = None
    for o in obs:
        p05, p95, spread = spread_of(o.zonals, min_zones)
        spreads.append(spread)
        if o.id == last.id:
            last_p05, last_p95, last_spread = p05, p95, spread
    if last_spread is None:
        last_p05, last_p95, last_spread = spread_of(last.zonals, min_zones)
    summary = summarize(spreads)
    body = summary.as_public("USD/MWh")
    body["lastSpread"] = last_spread
    body["lastP05"] = last_p05
    body["lastP95"] = last_p95
    body["zones"] = dict(sorted(last.zonals.items()))
    return body


def _points_lmp(obs: list[Observation]) -> list[dict[str, Any]]:
    return [
        {"t": o.ts.isoformat(), "value": o.rto_lmp}
        for o in obs
        if o.rto_lmp is not None
    ]


def _points_load(obs: list[Observation]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in obs:
        v = o.load_mw
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f):
            continue
        out.append({"t": o.ts.isoformat(), "value": f})
    return out


def _points_spread(obs: list[Observation], min_zones: int) -> list[dict[str, Any]]:
    out = []
    for o in obs:
        p05, p95, spread = spread_of(o.zonals, min_zones)
        if spread is None:
            continue
        out.append(
            {
                "t": o.ts.isoformat(),
                "spread": spread,
                "p05": p05,
                "p95": p95,
            }
        )
    return out


def _hourly(points: list[dict[str, Any]], value_key: str = "value") -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    extra: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for p in points:
        t = datetime.fromisoformat(p["t"])
        hour = t.replace(minute=0, second=0, microsecond=0).isoformat()
        if value_key == "spread":
            extra[hour].append((p["p05"], p["p95"]))
            buckets[hour].append(float(p["spread"]))
        else:
            buckets[hour].append(float(p[value_key]))
    out = []
    for hour in sorted(buckets):
        xs = buckets[hour]
        mean = sum(xs) / len(xs)
        item: dict[str, Any] = {"t": hour, "value": mean, "n": len(xs)}
        if hour in extra:
            p05s = [a for a, _ in extra[hour]]
            p95s = [b for _, b in extra[hour]]
            item = {
                "t": hour,
                "spread": mean,
                "p05": sum(p05s) / len(p05s),
                "p95": sum(p95s) / len(p95s),
                "n": len(xs),
            }
        out.append(item)
    return out


def assemble_latest(
    store: Store,
    settings: Settings,
    families: Iterable[Family] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    last = store.latest()
    if last is None:
        return None
    now = now or _now()
    start = now - timedelta(hours=settings.default_l1_window_hours)
    window = store.observations_since(start)
    if not window:
        window = [last]
    fams = tuple(families) if families else ALL_FAMILIES
    body = envelope(last, len(window), settings, now=now)
    if "rto_lmp" in fams:
        body["rtoLmp"] = _lmp_block(window)
    if "zonal_spread" in fams:
        body["zonalSpread"] = _spread_block(window, last, settings.min_zones_for_spread)
    if "rto_load" in fams:
        body["rtoLoad"] = _load_block(window, last)
    return body


def assemble_history(
    store: Store,
    settings: Settings,
    *,
    window_hours: int,
    families: Iterable[Family] | None = None,
    resolution: Literal["native", "hourly"] = "native",
    compare: Literal["none", "prior_period"] = "none",
    include_points: bool = True,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    last = store.latest()
    if last is None:
        return None
    now = now or _now()
    start = now - timedelta(hours=window_hours)
    window = store.observations_since(start)
    if not window:
        return None
    fams = tuple(families) if families else ALL_FAMILIES
    body = envelope(last, len(window), settings, now=now)
    body["windowHours"] = window_hours
    body["resolution"] = resolution
    min_z = settings.min_zones_for_spread

    def attach(target: dict[str, Any], series: list[Observation]) -> None:
        if "rto_lmp" in fams:
            block = _lmp_block(series)
            if include_points:
                pts = _points_lmp(series)
                block["points"] = _hourly(pts) if resolution == "hourly" else pts
            target["rtoLmp"] = block
        if "zonal_spread" in fams:
            block = _spread_block(series, series[-1], min_z)
            if include_points:
                pts = _points_spread(series, min_z)
                block["points"] = _hourly(pts, "spread") if resolution == "hourly" else pts
            target["zonalSpread"] = block
        if "rto_load" in fams:
            block = _load_block(series, series[-1])
            if include_points:
                pts = _points_load(series)
                # Need ≥2 finite points for a series/hist; avoid NaN ranges.
                if len(pts) >= 2:
                    block["points"] = _hourly(pts) if resolution == "hourly" else pts
                else:
                    block["points"] = []
            target["rtoLoad"] = block

    attach(body, window)
    if compare == "prior_period":
        prior_end = start
        prior_start = prior_end - timedelta(hours=window_hours)
        prior = store.observations_since(prior_start, prior_end)
        prior_body: dict[str, Any] = {
            "windowHours": window_hours,
            "observationCount": len(prior),
        }
        if prior:
            attach(prior_body, prior)
        body["priorPeriod"] = prior_body
    return body
