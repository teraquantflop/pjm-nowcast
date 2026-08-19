"""Intraday deviation histograms. Skip all-NaN series."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from pjm_nowcast.model.params import HIST_MIN_POINTS, HISTORY_MAX
from pjm_nowcast.model.state import FeatureVector, Snapshot

log = logging.getLogger("pjm_nowcast.model.histograms")
ET = ZoneInfo("America/New_York")
PLOTS_DIR = Path("plots")


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


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return dt.astimezone(ET)
    except Exception:
        return None


def todays_points(
    history: Optional[List[Dict[str, Any]]], now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    if not history:
        return []
    now = now or datetime.now(ET)
    today = now.astimezone(ET).date()
    out = []
    for h in history:
        dt = _parse_ts(h.get("ts", ""))
        if dt is None:
            continue
        if dt.date() == today:
            out.append(h)
    return out


def deviation_stats(values: List[float]) -> Tuple[float, float, List[float], float]:
    n = len(values)
    if n == 0:
        return float("nan"), float("nan"), [], float("nan")
    mean = sum(values) / n
    devs = [v - mean for v in values]
    if n >= 2:
        var = sum(d * d for d in devs) / (n - 1)
        std = math.sqrt(var)
    else:
        std = 0.0
    return mean, std, devs, devs[-1]


def _finite_series(pts: List[Dict[str, Any]], key: str) -> List[float]:
    out: List[float] = []
    for p in pts:
        try:
            v = float(p[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def _series_plottable(mean: float, std: float, devs: List[float], current_dev: float) -> bool:
    if not devs:
        return False
    if not math.isfinite(mean) or not math.isfinite(std) or not math.isfinite(current_dev):
        return False
    return all(math.isfinite(d) for d in devs)


def render_deviation_pngs(snap: Snapshot, feats: FeatureVector) -> Dict[str, Any]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    today_pts = todays_points(snap.history, feats.ts)
    n = len(today_pts)
    summary: Dict[str, Any] = {
        "n_today": n,
        "price_path": None,
        "load_path": None,
        "price_mean": None,
        "load_mean": None,
    }
    if n < HIST_MIN_POINTS:
        log.info("Histogram skipped — only %d point(s) today (need %d)", n, HIST_MIN_POINTS)
        return summary

    prices = _finite_series(today_pts, "price")
    loads = _finite_series(today_pts, "load_mw")
    day_tag = feats.ts.astimezone(ET).strftime("%Y%m%d")

    if prices:
        p_mean, p_std, p_devs, p_dev = deviation_stats(prices)
        summary["price_mean"] = p_mean
        if _series_plottable(p_mean, p_std, p_devs, p_dev):
            path = PLOTS_DIR / f"price_dev_{day_tag}.png"
            if _write_hist_png(path, p_devs, p_dev, p_std):
                summary["price_path"] = str(path)
        else:
            log.info("Price histogram skipped — non-finite deviations")
    else:
        log.info("Price histogram skipped — all-NaN / no finite prices today")

    if loads:
        l_mean, l_std, l_devs, l_dev = deviation_stats(loads)
        summary["load_mean"] = l_mean
        if _series_plottable(l_mean, l_std, l_devs, l_dev):
            path = PLOTS_DIR / f"load_dev_{day_tag}.png"
            if _write_hist_png(path, l_devs, l_dev, l_std):
                summary["load_path"] = str(path)
        else:
            log.info("Load histogram skipped — non-finite deviations")
    else:
        log.info("Load histogram skipped — all-NaN / no finite loads today")
    return summary


def _write_hist_png(path: Path, deviations: List[float], current_dev: float, std: float) -> bool:
    if (
        not deviations
        or not all(math.isfinite(d) for d in deviations)
        or not math.isfinite(current_dev)
    ):
        log.info("Histogram skipped — non-finite deviations (%s)", path.name)
        return False
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        log.info("Histogram skipped — matplotlib unavailable (%s)", exc)
        return False
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    n_bins = max(5, min(12, len(deviations)))
    ax.hist(deviations, bins=n_bins, color="#4C78A8", edgecolor="white", alpha=0.85)
    ax.axvline(current_dev, color="#E45756", linewidth=2.0)
    ax.axvline(0.0, color="#333333", linewidth=1.0, linestyle="--", alpha=0.7)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", path)
    return True
