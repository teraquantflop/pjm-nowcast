"""Empirical zonal-spread probability card. Not a forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pjm_nowcast import DISCLAIMER
from pjm_nowcast.db.store import Observation, Store, target_hour_ept
from pjm_nowcast.settings import Settings
from pjm_nowcast.spread_card import (
    LOOKBACK_DEFAULT,
    LOOKBACK_MAX,
    MIN_PAIRED_DAYS,
    SAMPLE_TAG,
    SPREAD_CARD_BUYER_BEWARE,
)
from pjm_nowcast.stats.descriptive import percentile, spread_of

ET = ZoneInfo("America/New_York")
# PJM on-peak HE 8–23 = hour-beginning 07:00–22:00 EPT, weekdays, not NERC holidays.
ON_PEAK_HB_HOURS = range(7, 23)


class InsufficientSample(Exception):
    """Fewer than MIN_PAIRED_DAYS paired on-peak days, or no quiet pool for K."""


class InvalidCardRequest(Exception):
    """Bad lookback or asOf."""


@dataclass(frozen=True)
class PairedHour:
    hour_ept: datetime
    ept_date: date
    spr_act: float
    spr_nc: float
    snapshot_asof: datetime


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ept(dt: datetime) -> datetime:
    return _as_utc(dt).astimezone(ET)


def _parse_iso(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return _as_utc(dt)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def _last_monday(year: int, month: int) -> date:
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != 0:
        d -= timedelta(days=1)
    return d


def nerc_holiday_dates(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),
        _last_monday(year, 5),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


def is_nerc_holiday(d: date) -> bool:
    return d in nerc_holiday_dates(d.year)


def is_on_peak_hour(hour_ept: datetime) -> bool:
    local = _ept(hour_ept).replace(minute=0, second=0, microsecond=0)
    if local.weekday() >= 5:
        return False
    if is_nerc_holiday(local.date()):
        return False
    return local.hour in ON_PEAK_HB_HOURS


def day_on_peak_complete(d: date, as_of: datetime) -> bool:
    """True when every on-peak hour-beginning on d has ended before as_of."""
    local = _ept(as_of)
    if d < local.date():
        return True
    if d > local.date():
        return False
    return local.hour >= 23


def _hour_dt(iso: str) -> datetime:
    return _parse_iso(iso)


def _closest_observation(
    candidates: list[Observation], snapshot_asof: datetime
) -> Observation | None:
    if not candidates:
        return None
    target = _as_utc(snapshot_asof)
    return min(candidates, key=lambda o: abs((_as_utc(o.ts) - target).total_seconds()))


def _pair_hours(
    store: Store,
    settings: Settings,
    *,
    as_of: datetime,
    lookback_days: int,
) -> list[PairedHour]:
    as_of = _as_utc(as_of)
    end_local = _ept(as_of)
    end_date = end_local.date()
    start_date = end_date - timedelta(days=lookback_days - 1)
    window_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=ET)
    window_start_utc = window_start.astimezone(timezone.utc)
    open_hour = target_hour_ept(as_of)

    snapshots = store.list_nowcast_snapshots(
        start=window_start_utc,
        end=as_of + timedelta(hours=1),
    )
    observations = store.observations_since(
        window_start_utc - timedelta(hours=1),
        as_of + timedelta(hours=1),
    )
    by_hour: dict[str, list[Observation]] = {}
    for obs in observations:
        key = target_hour_ept(obs.ts)
        by_hour.setdefault(key, []).append(obs)

    paired: list[PairedHour] = []
    for snap in snapshots:
        hour_s = snap.get("target_hour_ept")
        if not hour_s:
            continue
        if hour_s == open_hour:
            continue
        try:
            hour_dt = _hour_dt(str(hour_s))
        except ValueError:
            continue
        local = _ept(hour_dt).replace(minute=0, second=0, microsecond=0)
        if local.date() < start_date or local.date() > end_date:
            continue
        if local > end_local:
            continue
        if not is_on_peak_hour(local):
            continue
        spr_nc = snap.get("spr_nc")
        try:
            spr_nc_f = float(spr_nc)
        except (TypeError, ValueError):
            continue
        if spr_nc is None or not (spr_nc_f == spr_nc_f):  # NaN
            continue
        asof_s = snap.get("asof")
        try:
            snap_asof = _parse_iso(str(asof_s)) if asof_s else hour_dt
        except ValueError:
            snap_asof = hour_dt
        obs = _closest_observation(by_hour.get(hour_s, []), snap_asof)
        if obs is None:
            continue
        _p05, _p95, spr_act = spread_of(obs.zonals, settings.min_zones_for_spread)
        if spr_act is None:
            continue
        paired.append(
            PairedHour(
                hour_ept=local,
                ept_date=local.date(),
                spr_act=float(spr_act),
                spr_nc=float(spr_nc_f),
                snapshot_asof=snap_asof,
            )
        )
    paired.sort(key=lambda h: h.hour_ept)
    return paired


def _latest_nowcast_spr(
    store: Store,
    as_of: datetime,
) -> float | None:
    as_of = _as_utc(as_of)
    start = as_of - timedelta(days=2)
    rows = store.list_nowcast_snapshots(start=start, end=as_of + timedelta(seconds=1))
    best: float | None = None
    best_ts: datetime | None = None
    for snap in rows:
        raw = snap.get("spr_nc")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if raw is None:
            continue
        asof_s = snap.get("asof") or snap.get("target_hour_ept")
        try:
            ts = _parse_iso(str(asof_s))
        except ValueError:
            continue
        if ts > as_of:
            continue
        if best_ts is None or ts >= best_ts:
            best_ts = ts
            best = val
    return best


def assemble_probability_card(
    store: Store,
    settings: Settings,
    *,
    lookback_days: int = LOOKBACK_DEFAULT,
    as_of: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    if lookback_days < 1 or lookback_days > LOOKBACK_MAX:
        raise InvalidCardRequest(
            f"lookbackDays must be 1–{LOOKBACK_MAX}."
        )
    as_of = _as_utc(as_of or now or datetime.now(timezone.utc))
    if store.count() == 0 and not store.list_nowcast_snapshots():
        return None

    paired = _pair_hours(store, settings, as_of=as_of, lookback_days=lookback_days)
    by_day: dict[date, list[PairedHour]] = {}
    for row in paired:
        by_day.setdefault(row.ept_date, []).append(row)
    days = sorted(by_day)
    if len(days) < MIN_PAIRED_DAYS:
        raise InsufficientSample(
            f"Need at least {MIN_PAIRED_DAYS} paired on-peak days; got {len(days)}."
        )

    daily_maxes: list[float] = []
    quiet: list[float] = []
    day_max_hour: dict[date, PairedHour] = {}
    for d in days:
        hours = by_day[d]
        peak = max(hours, key=lambda h: (h.spr_act, h.hour_ept))
        day_max_hour[d] = peak
        daily_maxes.append(peak.spr_act)
        for h in hours:
            if h.hour_ept != peak.hour_ept:
                quiet.append(h.spr_act)

    k = percentile(quiet, 95)
    if k is None:
        raise InsufficientSample("Quiet high-water mark needs on-peak hours besides each day's max.")

    payoffs = [max(m - k, 0.0) for m in daily_maxes]
    hit_days = sum(1 for m in daily_maxes if m > k)
    day_count = len(days)
    hit_rate = hit_days / day_count
    avg_payoff = sum(payoffs) / day_count
    p50 = percentile(daily_maxes, 50)
    p95 = percentile(daily_maxes, 95)

    complete_days = [d for d in days if day_on_peak_complete(d, as_of)]
    latest_complete = complete_days[-1] if complete_days else None
    latest_block: dict[str, Any] | None = None
    if latest_complete is not None:
        peak = day_max_hour[latest_complete]
        latest_block = {
            "eptDate": latest_complete.isoformat(),
            "maxHourEpt": peak.hour_ept.isoformat(),
            "spr_act": peak.spr_act,
            "spr_nc": peak.spr_nc,
            "miss": peak.spr_act - peak.spr_nc,
        }

    latest_spr_nc = _latest_nowcast_spr(store, as_of)
    through = bool(latest_spr_nc is not None and latest_spr_nc > k)

    return {
        "product": "pjm-nowcast",
        "disclaimer": DISCLAIMER,
        "timezone": "America/New_York",
        "lookbackDays": lookback_days,
        "asOf": as_of.isoformat(),
        "sample": {
            "tag": SAMPLE_TAG,
            "dayCount": day_count,
            "firstEptDate": days[0].isoformat(),
            "lastEptDate": days[-1].isoformat(),
        },
        "K": k,
        "hitDays": hit_days,
        "hitRate": hit_rate,
        "avgPayoff": avg_payoff,
        "dailyMaxP50": p50,
        "dailyMaxP95": p95,
        "latestCompleteDay": latest_block,
        "latestNowcast": {
            "spr_nc": latest_spr_nc,
            "K": k,
            "throughStrike": through,
        },
        "buyerBeware": SPREAD_CARD_BUYER_BEWARE,
    }
