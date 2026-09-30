"""Turn stored observations into public response dicts."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.db.store import Observation, Store, target_hour_ept
from pjm_nowcast.settings import Settings
from pjm_nowcast.stats.descriptive import spread_of, summarize
from pjm_nowcast.stats.price_vol import PRICE_VOL_WINDOW, price_vol_from_lmps

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


def _price_vol_from_snapshot(settings: Settings) -> tuple[float | None, bool]:
    """Last sticky price_vol from snapshot.json last_features only.

    price_vol is rolling realized LMP std in $/MWh, not mix std / Black vol.
    Reads plain JSON — does not import pjm_nowcast.model.
    """
    path = getattr(settings, "snapshot_path", None)
    if path is None:
        return None, True
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, True
    if not isinstance(data, dict):
        return None, True
    lf = data.get("last_features")
    if not isinstance(lf, dict):
        return None, True
    flagged = bool(lf.get("price_vol_missing", False))
    try:
        vol = float(lf["price_vol"]) if lf.get("price_vol") is not None else None
    except (TypeError, ValueError):
        vol = None
    if flagged or vol is None or not math.isfinite(vol) or vol <= 0.0:
        return None, True
    return vol, False


def _price_vol_from_sqlite(store: Store) -> tuple[float | None, bool]:
    return price_vol_from_lmps(store.recent_rto_lmps(PRICE_VOL_WINDOW))


def _mix_from_sidecar(settings: Settings) -> tuple[float | None, int | None]:
    path = Path(getattr(settings, "data_dir", "") or "") / "mix.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    mix_std = data.get("mix_std_price")
    try:
        mix_f = float(mix_std) if mix_std is not None else None
        if mix_f is not None and (not math.isfinite(mix_f) or mix_f <= 0):
            mix_f = None
    except (TypeError, ValueError):
        mix_f = None
    n = data.get("n_obs")
    try:
        n_i = int(n) if n is not None else None
    except (TypeError, ValueError):
        n_i = None
    return mix_f, n_i


def resolve_price_vol(store: Store, settings: Settings) -> tuple[float | None, bool]:
    """Sticky last price_vol for /latest.

    Prefer RMS of the last 8 SQLite RTO LMP diffs (same as the poller) so a
    restart restores vol from the observation store. Fall back to snapshot.json
    last_features only when SQLite cannot form a window.
    """
    vol, missing = _price_vol_from_sqlite(store)
    if not missing:
        return vol, False
    return _price_vol_from_snapshot(settings)


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
    vol, missing = resolve_price_vol(store, settings)
    body["price_vol_missing"] = missing
    body["price_vol"] = None if missing else vol
    mix_std, mix_n = _mix_from_sidecar(settings)
    body["mix_std_price"] = mix_std
    body["mix_n_obs"] = mix_n
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


def assemble_regime(
    store: Store,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    last = store.latest()
    if last is None:
        return None
    body = envelope(last, 1, settings, now=now)
    path = getattr(settings, "snapshot_path", None)
    data: dict[str, Any] = {}
    try:
        raw = Path(path).read_text(encoding="utf-8") if path else ""
        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            data = parsed
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        data = {}
    posts = data.get("state_posteriors")
    post_list: list[float] | None = None
    k_star: int | None = None
    if isinstance(posts, list) and posts:
        try:
            vals = [float(p) for p in posts]
        except (TypeError, ValueError):
            vals = []
        if vals and all(math.isfinite(p) for p in vals):
            post_list = vals
            k_star = int(max(range(len(vals)), key=lambda i: vals[i]))
    if k_star is None:
        notes = str(data.get("notes") or "")
        if notes.startswith("k*="):
            try:
                k_star = int(notes.split("=", 1)[1].strip())
            except (TypeError, ValueError):
                k_star = None
    ent = data.get("last_entropy")
    try:
        ent_f = float(ent) if ent is not None else None
        if ent_f is not None and not math.isfinite(ent_f):
            ent_f = None
    except (TypeError, ValueError):
        ent_f = None
    body["entropy"] = ent_f
    body["posteriors"] = post_list
    body["kStar"] = k_star
    return body


def assemble_spreads(
    store: Store,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    last = store.latest()
    if last is None:
        return None
    body = envelope(last, 1, settings, now=now)
    block = _spread_block([last], last, settings.min_zones_for_spread)
    body["zones"] = block.get("zones")
    body["lastSpread"] = block.get("lastSpread")
    body["lastP05"] = block.get("lastP05")
    body["lastP95"] = block.get("lastP95")
    body["unit"] = block.get("unit")
    return body


def assemble_asof(
    store: Store,
    settings: Settings,
    as_of: datetime,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    pinned = store.at_or_before(as_of)
    if pinned is None:
        return None
    start = as_of - timedelta(hours=settings.default_l1_window_hours)
    window = [o for o in store.observations_since(start) if o.ts <= as_of]
    if not window:
        window = [pinned]
    body = envelope(pinned, len(window), settings, now=now)
    body["pinnedAsOf"] = as_of.isoformat()
    if "rto_lmp" in ALL_FAMILIES:
        body["rtoLmp"] = _lmp_block(window)
    body["zonalSpread"] = _spread_block(window, pinned, settings.min_zones_for_spread)
    body["rtoLoad"] = _load_block(window, pinned)
    return body


def snapshot_record_from_latest(body: dict[str, Any], fetched_at: datetime) -> dict[str, Any] | None:
    asof_s = body.get("asOf")
    if not asof_s:
        return None
    try:
        asof = datetime.fromisoformat(str(asof_s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    zs = body.get("zonalSpread") or {}
    zones = zs.get("zones") if isinstance(zs, dict) else None
    zone_json = json.dumps(zones) if isinstance(zones, dict) and zones else None
    spr = zs.get("lastSpread") if isinstance(zs, dict) else None
    rto = (body.get("rtoLmp") or {}).get("last") if isinstance(body.get("rtoLmp"), dict) else None
    load = (body.get("rtoLoad") or {}).get("last") if isinstance(body.get("rtoLoad"), dict) else None
    return {
        "fetched_at_utc": fetched_at.astimezone(timezone.utc).isoformat(),
        "asof": asof.isoformat(),
        "target_hour_ept": target_hour_ept(asof),
        "rto_nc": rto,
        "zone_nc": zone_json,
        "spr_nc": spr,
        "load_nc": load,
        "price_vol": body.get("price_vol"),
        "price_vol_missing": body.get("price_vol_missing"),
        "mix_std_price": body.get("mix_std_price"),
        "mix_n_obs": body.get("mix_n_obs"),
    }


def assemble_snapshots(
    store: Store,
    settings: Settings,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now()
    cap_start = now - timedelta(days=settings.max_history_days)
    if start is None or start < cap_start:
        start = cap_start
    rows = store.list_nowcast_snapshots(start=start, end=end)
    return {
        "product": "pjm-nowcast",
        "disclaimer": (
            DISCLAIMER
            + " Append-only snapshots of what /latest reported for that EPT hour-beginning. "
            "Not a forward forecast of a future hour. Hours without a row have no stored nowcast (null, not zero). "
            "Residuals are only defined where a snapshot exists."
        ),
        "windowDays": settings.max_history_days,
        "from": start.isoformat(),
        "to": None if end is None else end.isoformat(),
        "count": len(rows),
        "snapshots": rows,
    }
