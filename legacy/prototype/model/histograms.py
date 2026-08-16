"""
Intraday deviation-from-mean histograms (PNG) for load and price.

Deviations are relative to the mean of *today's* samples (Eastern date).
Current tick is marked with a vertical line so you can see left/center/right tail.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from config import HIST_MIN_POINTS, HISTORY_MAX, PLOTS_DIR
from .state import FeatureVector, Snapshot

log = logging.getLogger("shpnwels.histograms")
ET = ZoneInfo("America/New_York")


def append_history(snap: Snapshot, feats: FeatureVector) -> None:
    """Push current observation onto the ring buffer (cap HISTORY_MAX)."""
    if snap.history is None:
        snap.history = []
    entry = {
        "ts": feats.ts.isoformat() if feats.ts.tzinfo else feats.ts.replace(tzinfo=ET).isoformat(),
        "load_mw": float(feats.load_mw),
        "price": float(feats.price),
    }
    if snap.zonal_spread is not None:
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


def todays_points(history: Optional[List[Dict[str, Any]]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
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


def deviation_stats(
    values: List[float],
) -> Tuple[float, float, List[float], float]:
    """
    Returns (mean, std, deviations, current_dev) where current_dev is
    the last value's deviation. std is sample std (n-1) if n>=2 else 0.
    """
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


def _z_label(z: float) -> str:
    if not math.isfinite(z):
        return "n/a"
    if z <= -2.0:
        return "far left tail"
    if z <= -1.0:
        return "left of center"
    if z < 1.0:
        return "near center"
    if z < 2.0:
        return "right of center"
    return "far right tail"


def render_deviation_pngs(
    snap: Snapshot,
    feats: FeatureVector,
) -> Dict[str, Any]:
    """
    Build today's deviation histograms for price and load.
    Writes PNGs under PLOTS_DIR; returns summary dict for status print.
    """
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    today_pts = todays_points(snap.history, feats.ts)
    n = len(today_pts)

    summary: Dict[str, Any] = {
        "n_today": n,
        "price_path": None,
        "load_path": None,
        "price_mean": None,
        "price_std": None,
        "price_dev": None,
        "price_z": None,
        "price_pos": None,
        "load_mean": None,
        "load_std": None,
        "load_dev": None,
        "load_z": None,
        "load_pos": None,
        "peak_today": snap.forecast_peak_today_mw,
        "peak_tomorrow": snap.forecast_peak_tomorrow_mw,
    }

    if n < HIST_MIN_POINTS:
        log.info("Histogram skipped — only %d point(s) today (need %d)", n, HIST_MIN_POINTS)
        return summary

    prices = [float(p["price"]) for p in today_pts]
    loads = [float(p["load_mw"]) for p in today_pts]

    p_mean, p_std, p_devs, p_dev = deviation_stats(prices)
    l_mean, l_std, l_devs, l_dev = deviation_stats(loads)
    p_z = p_dev / p_std if p_std > 1e-9 else 0.0
    l_z = l_dev / l_std if l_std > 1e-9 else 0.0

    summary.update(
        {
            "price_mean": p_mean,
            "price_std": p_std,
            "price_dev": p_dev,
            "price_z": p_z,
            "price_pos": _z_label(p_z),
            "load_mean": l_mean,
            "load_std": l_std,
            "load_dev": l_dev,
            "load_z": l_z,
            "load_pos": _z_label(l_z),
        }
    )

    day_tag = feats.ts.astimezone(ET).strftime("%Y%m%d")
    price_path = PLOTS_DIR / f"price_dev_{day_tag}.png"
    load_path = PLOTS_DIR / f"load_dev_{day_tag}.png"

    try:
        _write_hist_png(
            path=price_path,
            deviations=p_devs,
            current_dev=p_dev,
            mean=p_mean,
            std=p_std,
            z=p_z,
            title=f"SHPNWELS price deviations — {feats.ts.astimezone(ET).strftime('%Y-%m-%d %H:%M %Z')}",
            xlabel="Price − today's mean ($/MWh)",
            unit_mean=f"today μ = ${p_mean:.2f}   σ = ${p_std:.2f}   n = {n}",
            current_label=f"now ${feats.price:.2f}  (dev {p_dev:+.2f}, z={p_z:+.2f})",
            peak_note=_tomorrow_note(snap, kind="price"),
        )
        summary["price_path"] = str(price_path)
    except Exception as e:
        log.warning("Price histogram failed: %s", e)

    try:
        _write_hist_png(
            path=load_path,
            deviations=l_devs,
            current_dev=l_dev,
            mean=l_mean,
            std=l_std,
            z=l_z,
            title=f"SHPNWELS load deviations — {feats.ts.astimezone(ET).strftime('%Y-%m-%d %H:%M %Z')}",
            xlabel="Load − today's mean (MW)",
            unit_mean=f"today μ = {l_mean:,.0f} MW   σ = {l_std:,.0f} MW   n = {n}",
            current_label=f"now {feats.load_mw:,.0f} MW  (dev {l_dev:+,.0f}, z={l_z:+.2f})",
            peak_note=_tomorrow_note(snap, kind="load"),
        )
        summary["load_path"] = str(load_path)
    except Exception as e:
        log.warning("Load histogram failed: %s", e)

    return summary


def _tomorrow_note(snap: Snapshot, kind: str) -> str:
    pt = snap.forecast_peak_today_mw
    pm = snap.forecast_peak_tomorrow_mw
    if kind == "load":
        parts = []
        if pt is not None:
            parts.append(f"official peak today {pt:,.0f} MW")
        if pm is not None:
            parts.append(f"tomorrow {pm:,.0f} MW")
            if pt is not None:
                delta = pm - pt
                parts.append(f"Δ {delta:+,.0f} MW")
        return "  |  ".join(parts) if parts else "no official peaks yet"
    # price: no official peak — soft regime hint only
    if snap.last_high_spread:
        return "spread regime: HIGH (elevated zonal disparity)"
    if snap.zonal_spread is not None:
        return f"zonal spread ≈ {snap.zonal_spread:.1f} $/MWh"
    return "no official price peak — regime via mix / spread"


def _write_hist_png(
    path: Path,
    deviations: List[float],
    current_dev: float,
    mean: float,
    std: float,
    z: float,
    title: str,
    xlabel: str,
    unit_mean: str,
    current_label: str,
    peak_note: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)

    n_bins = max(5, min(12, len(deviations)))
    ax.hist(
        deviations,
        bins=n_bins,
        color="#4C78A8",
        edgecolor="white",
        alpha=0.85,
        label="today's deviations",
    )

    # vertical line at current deviation
    ax.axvline(current_dev, color="#E45756", linewidth=2.0, label=current_label)
    # zero = today's mean
    ax.axvline(0.0, color="#333333", linewidth=1.0, linestyle="--", alpha=0.7, label="today mean (0)")

    if std > 1e-9:
        for k, style in [(1, ":"), (2, ":")]:
            ax.axvline(+k * std, color="#F58518", linewidth=1.0, linestyle=style, alpha=0.6)
            ax.axvline(-k * std, color="#F58518", linewidth=1.0, linestyle=style, alpha=0.6)

    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    footer = f"{unit_mean}\n{current_label}  →  {_z_label(z)}\n{peak_note}"
    fig.text(0.01, 0.01, footer, fontsize=8, va="bottom", ha="left", family="monospace")

    fig.tight_layout(rect=[0, 0.12, 1, 1])
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    log.info("Wrote %s", path)
