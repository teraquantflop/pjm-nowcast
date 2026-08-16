#!/usr/bin/env python3
"""
SHPNWELS – Short-Horizon Probabilistic Nowcaster With Emerging Latent Structure

Local prototype loop:
  scrape → features → online HMM update → persist → sleep (with jitter)
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import (
    HIGH_INFO_END_HOUR,
    HIGH_INFO_INTERVAL_MIN,
    HIGH_INFO_JITTER_MIN,
    HIGH_INFO_START_HOUR,
    LOG_PATH,
    MOCK_MODE,
    OFF_HOURS_INTERVAL_MIN,
    OFF_HOURS_JITTER_MIN,
    SNAPSHOT_PATH,
)
from data.features import build_features
from data.scraper import fetch_pjm_markets_page
from model.histograms import render_deviation_pngs
from model.hmm import predictive_summary, update
from model.persistence import load_snapshot, save_snapshot
from model.tails import residual_scales
from model.zonal import headroom_mw, predictor_bands

ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger("shpnwels")


def next_sleep_seconds() -> float:
    now = datetime.now(ET)
    hour = now.hour

    if HIGH_INFO_START_HOUR <= hour < HIGH_INFO_END_HOUR:
        base = HIGH_INFO_INTERVAL_MIN
        jitter = HIGH_INFO_JITTER_MIN
        window = "high-info"
    else:
        base = OFF_HOURS_INTERVAL_MIN
        jitter = OFF_HOURS_JITTER_MIN
        window = "off-hours"

    delta = random.uniform(-jitter, jitter)
    minutes = max(5.0, base + delta)
    log.info(
        "Next sleep: %.1f min  (window=%s, base=%d, jitter=±%d)",
        minutes,
        window,
        base,
        jitter,
    )
    return minutes * 60.0


def print_status(snap, feats, summary: dict, hist: dict | None = None) -> None:
    scales = residual_scales(snap)
    warm = "  [warm]" if summary.get("warm") else ""

    load_mu = summary.get("mix_mean_load", float("nan"))
    load_sd = summary.get("mix_std_load", float("nan"))
    price_mu = summary.get("mix_mean_price", float("nan"))
    price_sd = summary.get("mix_std_price", float("nan"))
    lb = predictor_bands(load_mu, load_sd)
    pb = predictor_bands(price_mu, price_sd)

    hr = headroom_mw(snap, feats.load_mw)
    peak_s = (
        f"{snap.forecast_peak_today_mw:,.0f}"
        if snap.forecast_peak_today_mw is not None
        else "?"
    )
    hr_s = f"{hr:+,.0f}" if hr is not None else "?"

    peak_tom = snap.forecast_peak_tomorrow_mw
    peak_tom_s = f"{peak_tom:,.0f}" if peak_tom is not None else "?"
    if (
        snap.forecast_peak_today_mw is not None
        and peak_tom is not None
    ):
        dpeak = peak_tom - snap.forecast_peak_today_mw
        dpeak_s = f"{dpeak:+,.0f}"
    else:
        dpeak_s = "?"

    spread = snap.zonal_spread
    p05 = snap.zonal_p05
    p95 = snap.zonal_p95
    if spread is not None and p05 is not None and p95 is not None:
        spread_line = (
            f"  zonal_spread p05/p95 ≈ {p05:.1f} / {p95:.1f}  "
            f"spread={spread:.1f}"
            + ("  [high]" if snap.last_high_spread else "")
        )
    else:
        spread_line = "  zonal_spread n/a"

    # intraday spread trajectory
    if snap.spread_n_today and snap.spread_max_today is not None:
        smin = snap.spread_min_today
        smax = snap.spread_max_today
        n_hi = int(snap.spread_high_count_today or 0)
        n_sp = int(snap.spread_n_today or 0)
        traj_line = (
            f"  spread_today  min={smin:.1f}  max={smax:.1f}  "
            f"[high]={n_hi}/{n_sp}"
        )
    else:
        traj_line = "  spread_today  n/a"

    print("=" * 72)
    print(f"  obs #{snap.n_obs}   {feats.ts.strftime('%Y-%m-%d %H:%M %Z')}{warm}")
    print(f"  load={feats.load_mw:,.0f} MW   ramp={feats.load_ramp:+.0f}")
    print(f"  price={feats.price:.2f}   price_vol={feats.price_vol:.2f}")
    print(f"  forecast_peak_today={peak_s}  headroom={hr_s} MW")
    print(f"  forecast_peak_tomorrow={peak_tom_s}  Δ vs today={dpeak_s} MW")
    print(spread_line)
    print(traj_line)
    print(f"  quality={feats.quality:.2f}")
    print(
        f"  entropy={summary.get('entropy', float('nan')):.3f}   "
        f"dominant_state={summary.get('dominant_state')}"
    )
    print(f"  posteriors={summary.get('posteriors')}")
    print(
        f"  mix load  μ={load_mu:,.0f}  σ={load_sd:,.0f}  "
        f"+2σ={lb['p2']:,.0f}  ~95%={lb['p95']:,.0f}"
    )
    print(
        f"  mix price μ={price_mu:.2f}  σ={price_sd:.2f}  "
        f"+2σ={pb['p2']:.2f}  ~95%={pb['p95']:.2f}"
    )
    print(
        f"  residual scales (scaled space): "
        f"load={scales.get('load_mw', float('nan')):.2f}  "
        f"price={scales.get('price', float('nan')):.2f}"
    )
    lo = snap.cond_price_resid_low_spread
    hi = snap.cond_price_resid_high_spread
    if lo is not None or hi is not None:
        lo_s = f"{lo:.3f}" if lo is not None else "n/a"
        hi_s = f"{hi:.3f}" if hi is not None else "n/a"
        print(f"  cond price scale | low_spread={lo_s}  high_spread={hi_s}")

    if hist:
        n = hist.get("n_today", 0)
        print(f"  --- intraday deviation hist (n_today={n}) ---")
        if hist.get("price_z") is not None:
            print(
                f"  price dev={hist['price_dev']:+.2f}  z={hist['price_z']:+.2f}  "
                f"({hist.get('price_pos')})  today μ=${hist['price_mean']:.2f}"
            )
        if hist.get("load_z") is not None:
            print(
                f"  load  dev={hist['load_dev']:+,.0f}  z={hist['load_z']:+.2f}  "
                f"({hist.get('load_pos')})  today μ={hist['load_mean']:,.0f} MW"
            )
        if hist.get("price_path"):
            print(f"  PNG price → {hist['price_path']}")
        if hist.get("load_path"):
            print(f"  PNG load  → {hist['load_path']}")
        if n < 3:
            print("  (PNGs start after ≥3 points today)")

    print("=" * 72)


def run_forever() -> None:
    log.info("SHPNWELS starting  mock_mode=%s  snapshot=%s", MOCK_MODE, SNAPSHOT_PATH)
    snap = load_snapshot(SNAPSHOT_PATH)
    last_raw = None

    if snap.last_features is not None:
        last_raw = {
            "load_mw": snap.last_features.load_mw,
            "rto_lmp": snap.last_features.price,
            "quality": snap.last_features.quality,
            "forecast_peak_today_mw": snap.last_features.forecast_peak_today_mw,
            "forecast_peak_tomorrow_mw": snap.last_features.forecast_peak_tomorrow_mw,
            "zonal_lmps": snap.last_features.zonal_lmps or {},
        }

    while True:
        try:
            raw = fetch_pjm_markets_page(previous=last_raw)
            last_raw = raw

            feats = build_features(raw, snap.last_features)
            snap = update(snap, feats)
            hist = render_deviation_pngs(snap, feats)
            save_snapshot(SNAPSHOT_PATH, snap)

            summary = predictive_summary(snap)
            print_status(snap, feats, summary, hist)

        except KeyboardInterrupt:
            log.info("Interrupted — saving and exiting")
            save_snapshot(SNAPSHOT_PATH, snap)
            break
        except Exception:
            log.exception("Cycle failed; will retry after sleep")

        time.sleep(next_sleep_seconds())


if __name__ == "__main__":
    run_forever()
