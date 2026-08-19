"""Guards against HMM NaN poison, missing price_vol, high-spread floor, hist skip."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from pjm_nowcast.model.hmm import predictive_summary, update
from pjm_nowcast.model.histograms import render_deviation_pngs
from pjm_nowcast.model.persistence import reset_hmm
from pjm_nowcast.model.state import FeatureVector, Snapshot
from pjm_nowcast.model.zonal import update_zonal_and_peak
from pjm_nowcast.poller.job import want_hmm_reset
from pjm_nowcast.settings import Settings

ET = ZoneInfo("America/New_York")
NAN = float("nan")


def _feats(**kw) -> FeatureVector:
    now = datetime.now(ET)
    defaults = dict(
        ts=now,
        load_mw=100_000.0,
        load_ramp=100.0,
        price=40.0,
        price_vol=5.0,
        hour_sin=0.0,
        hour_cos=1.0,
        is_weekend=0,
        quality=1.0,
        price_vol_missing=False,
        zonal_lmps={
            "BGE": 40.0,
            "COMED": 38.0,
            "DOM": 41.0,
            "PEPCO": 39.5,
            "PSEG": 42.0,
            "JCPL": 37.0,
        },
    )
    defaults.update(kw)
    return FeatureVector(**defaults)


def test_nan_load_yields_finite_posteriors():
    snap = Snapshot(n_states=5, n_obs=0)
    feats = _feats(load_mw=NAN, load_ramp=NAN)
    snap = update(snap, feats)
    assert snap.state_posteriors is not None
    assert all(math.isfinite(p) for p in snap.state_posteriors)
    assert math.isfinite(snap.last_entropy)
    assert abs(sum(snap.state_posteriors) - 1.0) < 1e-5
    assert snap.notes != "hmm_skip_nan"


def test_poisoned_from_dict_cold_starts():
    d = {
        "version": 1,
        "n_obs": 304,
        "n_states": 5,
        "transition_counts": [[NAN] * 5 for _ in range(5)],
        "emission_mean": [[NAN] * 6 for _ in range(5)],
        "emission_var": [[NAN] * 6 for _ in range(5)],
        "state_posteriors": [NAN] * 5,
        "residual_abs_ewm": [NAN] * 6,
        "last_entropy": NAN,
        "ewm": {"load_mw": {"mean": NAN, "var": NAN, "n": 304.0}},
        "history": [
            {"ts": datetime.now(ET).isoformat(), "load_mw": 100000.0, "price": 40.0}
        ],
        "spread_day": "2026-08-19",
        "spread_n_today": 18,
        "zonal_spread": 25.6,
    }
    snap = Snapshot.from_dict(d)
    assert snap.state_posteriors is None
    assert snap.emission_mean is None
    assert snap.emission_var is None
    assert snap.transition_counts is None
    assert snap.residual_abs_ewm is None
    assert snap.last_entropy == 0.0
    assert snap.n_obs == 304
    assert len(snap.history) == 1
    assert snap.spread_day == "2026-08-19"
    assert snap.zonal_spread == 25.6
    snap = update(snap, _feats())
    assert all(math.isfinite(p) for p in snap.state_posteriors)
    summary = predictive_summary(snap)
    assert summary.get("status") != "poisoned"
    assert math.isfinite(summary["entropy"])
    assert abs(sum(summary["posteriors"]) - 1.0) < 1e-3


def test_reset_hmm_keeps_history_and_zonal():
    snap = Snapshot(
        n_obs=304,
        n_states=5,
        transition_counts=[[1.0] * 5 for _ in range(5)],
        emission_mean=[[0.1] * 6 for _ in range(5)],
        emission_var=[[2.0] * 6 for _ in range(5)],
        state_posteriors=[0.2] * 5,
        residual_abs_ewm=[0.3] * 6,
        history=[{"ts": "2026-08-19T12:00:00-04:00", "load_mw": 1.0, "price": 2.0}],
        spread_day="2026-08-19",
        spread_n_today=7,
        zonal_spread=22.0,
        last_good_price_vol=8.5,
    )
    snap = reset_hmm(snap)
    assert snap.transition_counts is None
    assert snap.emission_mean is None
    assert snap.state_posteriors is None
    assert snap.n_obs == 0
    assert snap.notes == "HMM reset"
    assert len(snap.history) == 1
    assert snap.spread_day == "2026-08-19"
    assert snap.spread_n_today == 7
    assert snap.zonal_spread == 22.0
    assert snap.last_good_price_vol == 8.5


def test_missing_price_vol_skips_dim():
    snap = Snapshot(n_states=5, n_obs=0)
    feats = _feats(price_vol=0.0, price_vol_missing=True)
    snap = update(snap, feats)
    var = snap.emission_var
    assert all(math.isfinite(v) for row in var for v in row)
    for k in range(5):
        assert var[k][3] == 4.0


def test_last_good_price_vol_is_used():
    snap = Snapshot(n_states=5, n_obs=0, last_good_price_vol=12.0)
    feats = _feats(price_vol=0.0, price_vol_missing=True)
    snap = update(snap, feats)
    means = [row[3] for row in snap.emission_mean]
    assert any(abs(m) > 1e-9 for m in means)
    assert any(abs(snap.emission_var[k][3] - 4.0) > 1e-9 for k in range(5))


def test_abs_floor_flags_spread_37():
    from pjm_nowcast.settings import reset_settings_cache

    reset_settings_cache()
    snap = Snapshot(n_obs=100, zonal_spread_mean=22.0, zonal_spread_var=3545.0)
    feats = _feats(
        zonal_lmps={
            "BGE": 10.0,
            "COMED": 10.0,
            "DOM": 10.0,
            "PEPCO": 47.0,
            "PSEG": 47.0,
            "JCPL": 47.0,
        }
    )
    update_zonal_and_peak(snap, feats)
    assert snap.zonal_spread >= 30.0
    assert snap.last_high_spread is True
    assert snap.spread_high_count_today == 1


def test_all_nan_load_skips_load_hist(tmp_path):
    now = datetime.now(ET)
    history = [
        {"ts": now.isoformat(), "load_mw": NAN, "price": 40.0 + i} for i in range(4)
    ]
    snap = Snapshot(history=history, n_obs=4)
    feats = _feats(ts=now, price=44.0, load_mw=NAN)
    with patch("pjm_nowcast.model.histograms.PLOTS_DIR", Path(tmp_path)):
        summary = render_deviation_pngs(snap, feats)
    assert summary["load_path"] is None


def test_all_nan_both_series_no_png(tmp_path):
    now = datetime.now(ET)
    history = [{"ts": now.isoformat(), "load_mw": NAN, "price": NAN} for _ in range(4)]
    snap = Snapshot(history=history, n_obs=4)
    feats = _feats(ts=now, load_mw=NAN, price=NAN)
    with patch("pjm_nowcast.model.histograms.PLOTS_DIR", Path(tmp_path)):
        summary = render_deviation_pngs(snap, feats)
    assert summary["load_path"] is None
    assert summary["price_path"] is None
    assert list(Path(tmp_path).glob("*.png")) == []


def test_poisoned_summary_status():
    snap = Snapshot(n_obs=304, notes="hmm_skip_nan", state_posteriors=[NAN] * 5)
    summary = predictive_summary(snap)
    assert summary["status"] == "poisoned"
    assert summary["entropy"] is None


def test_want_hmm_reset_env_and_cli():
    s = Settings(env="test", pjm_nowcast_reset_hmm=False, run_poller=False, x402_disabled=True)
    assert want_hmm_reset(s, argv=["python", "-m", "pjm_nowcast.poller"]) is False
    assert want_hmm_reset(s, argv=["python", "--reset-hmm"]) is True
    s2 = Settings(env="test", pjm_nowcast_reset_hmm=True, run_poller=False, x402_disabled=True)
    assert want_hmm_reset(s2, argv=["python"]) is True


def test_build_features_price_vol_missing_then_carry():
    from pjm_nowcast.ingest import features as featmod

    featmod._price_history.clear()
    ts = datetime.now(ET)
    raw = {
        "ts": ts,
        "load_mw": 100_000.0,
        "rto_lmp": 30.0,
        "quality": 1.0,
        "zonal_lmps": {"BGE": 30.0},
    }
    f1 = featmod.build_features(raw, None)
    assert f1.price_vol_missing is True
    assert f1.price_vol == 0.0

    f2 = featmod.build_features({**raw, "rto_lmp": 31.0}, f1)
    assert f2.price_vol_missing is True

    f3 = featmod.build_features({**raw, "rto_lmp": 34.0}, f2)
    assert f3.price_vol_missing is False
    assert f3.price_vol > 0.0

    featmod._price_history.clear()
    f4 = featmod.build_features({**raw, "rto_lmp": 40.0}, f3)
    assert f4.price_vol_missing is True
    assert f4.price_vol == f3.price_vol


def test_poll_once_hmm_sidecar_writes_finite_snapshot(tmp_path):
    from pjm_nowcast.db.store import Store
    from pjm_nowcast.poller.job import poll_once

    settings = Settings(
        mock_mode=True,
        run_poller=False,
        database_path=tmp_path / "p.sqlite",
        data_dir=tmp_path,
        snapshot_path=tmp_path / "snapshot.json",
        env="test",
        x402_disabled=True,
    )
    store = Store(settings.database_path)
    snap = Snapshot(n_states=5)
    oid = poll_once(store, settings, retry_delays=(0,), snap=snap)
    assert oid is not None
    assert store.count() == 1
    assert snap.state_posteriors is not None
    assert all(math.isfinite(p) for p in snap.state_posteriors)
    assert abs(sum(snap.state_posteriors) - 1.0) < 1e-5
    assert math.isfinite(snap.last_entropy)
    assert (tmp_path / "snapshot.json").exists()
    summary = predictive_summary(snap)
    assert summary.get("status") != "poisoned"
    store.close()
