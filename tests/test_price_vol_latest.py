from __future__ import annotations

import json
from pathlib import Path

from pjm_nowcast.ingest.features import restore_price_history
from pjm_nowcast.stats.assemble import assemble_latest
from pjm_nowcast.stats.descriptive import sample_std
from pjm_nowcast.stats.price_vol import PRICE_VOL_WINDOW, rms_price_vol
from tests.conftest import seed_observation


def _write_features(path: Path, *, price_vol, price_vol_missing: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_features": {
                    "price_vol": price_vol,
                    "price_vol_missing": price_vol_missing,
                }
            }
        ),
        encoding="utf-8",
    )


def test_latest_includes_snapshot_price_vol(client, store, settings):
    seed_observation(store, hours_ago=1.0, rto_lmp=20.0)
    seed_observation(store, hours_ago=0.1, rto_lmp=40.0)
    snap = Path(settings.snapshot_path)
    _write_features(snap, price_vol=2.5, price_vol_missing=False)

    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["price_vol"] == 2.5
    assert body["price_vol_missing"] is False
    std = body["rtoLmp"]["std"]
    assert std is not None
    assert std != body["price_vol"]
    assert "entropy" not in body
    assert "posteriors" not in body
    assert "mix_mean_price" not in body
    assert "last_high_spread" not in body


def test_latest_price_vol_without_rto_lmp_family(client, store, settings):
    seed_observation(store, hours_ago=0.1)
    _write_features(
        Path(settings.snapshot_path), price_vol=2.5, price_vol_missing=False
    )
    r = client.post("/v1/nowcast/latest", json={"families": ["rto_load"]})
    assert r.status_code == 200
    body = r.json()
    assert "rtoLmp" not in body
    assert body["price_vol"] == 2.5
    assert body["price_vol_missing"] is False


def test_latest_missing_snapshot(client, store, settings):
    seed_observation(store, hours_ago=0.1)
    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["price_vol_missing"] is True
    assert body.get("price_vol") is None


def test_latest_price_vol_flagged_or_zero(client, store, settings):
    seed_observation(store, hours_ago=0.1)
    snap = Path(settings.snapshot_path)

    _write_features(snap, price_vol=2.5, price_vol_missing=True)
    body = client.post("/v1/nowcast/latest", json={}).json()
    assert body["price_vol_missing"] is True
    assert body.get("price_vol") is None

    _write_features(snap, price_vol=0, price_vol_missing=False)
    body = client.post("/v1/nowcast/latest", json={}).json()
    assert body["price_vol_missing"] is True
    assert body.get("price_vol") is None

    _write_features(snap, price_vol=None, price_vol_missing=False)
    body = client.post("/v1/nowcast/latest", json={}).json()
    assert body["price_vol_missing"] is True
    assert body.get("price_vol") is None


def test_history_does_not_include_price_vol(client, store, settings):
    seed_observation(store, hours_ago=0.1)
    _write_features(
        Path(settings.snapshot_path), price_vol=2.5, price_vol_missing=False
    )
    r = client.post("/v1/nowcast/history", json={"windowHours": 24})
    assert r.status_code == 200
    body = r.json()
    assert "price_vol" not in body
    assert "price_vol_missing" not in body


def test_assemble_latest_helper_reads_plain_json(store, settings, tmp_path):
    seed_observation(store, hours_ago=0.1, rto_lmp=30.0)
    _write_features(
        Path(settings.snapshot_path), price_vol=3.25, price_vol_missing=False
    )
    body = assemble_latest(store, settings)
    assert body is not None
    assert body["price_vol"] == 3.25
    assert body["price_vol_missing"] is False


def test_rms_price_vol_matches_poller_window():
    prices = [10.0, 12.0, 11.0]
    diffs = [2.0, -1.0]
    expected = (sum(d * d for d in diffs) / len(diffs)) ** 0.5
    assert rms_price_vol(prices) == expected
    assert rms_price_vol(prices[:2]) is None
    assert rms_price_vol([5.0, 5.0, 5.0]) is None


def test_latest_rebuilds_price_vol_from_sqlite_without_snapshot(client, store):
    prices = [20.0, 22.0, 19.0, 25.0, 24.0, 30.0, 28.0, 31.0]
    for i, px in enumerate(prices):
        seed_observation(store, hours_ago=float(len(prices) - i), rto_lmp=px)
    expected = rms_price_vol(prices)
    assert expected is not None

    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["price_vol_missing"] is False
    assert body["price_vol"] == expected
    mix = sample_std(prices)
    assert mix is not None
    assert mix != body["price_vol"]


def test_sqlite_vol_wins_over_flagged_snapshot(client, store, settings):
    prices = [10.0, 14.0, 11.0]
    for i, px in enumerate(prices):
        seed_observation(store, hours_ago=float(len(prices) - i), rto_lmp=px)
    _write_features(
        Path(settings.snapshot_path), price_vol=2.5, price_vol_missing=True
    )
    body = client.post("/v1/nowcast/latest", json={}).json()
    assert body["price_vol"] == rms_price_vol(prices)
    assert body["price_vol_missing"] is False


def test_recent_rto_lmps_oldest_first_skips_null(store):
    seed_observation(store, hours_ago=3.0, rto_lmp=10.0)
    seed_observation(store, hours_ago=2.0, rto_lmp=None)
    seed_observation(store, hours_ago=1.0, rto_lmp=12.0)
    seed_observation(store, hours_ago=0.0, rto_lmp=11.0)
    assert store.recent_rto_lmps(8) == [10.0, 12.0, 11.0]
    assert store.recent_rto_lmps(2) == [12.0, 11.0]


def test_restore_price_history_from_sqlite(store):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from pjm_nowcast.ingest import features as featmod

    prices = [30.0, 31.0, 34.0]
    for i, px in enumerate(prices):
        seed_observation(store, hours_ago=float(len(prices) - i), rto_lmp=px)
    featmod._price_history.clear()
    n = restore_price_history(store.recent_rto_lmps(PRICE_VOL_WINDOW))
    assert n == 3
    assert list(featmod._price_history) == prices
    assert rms_price_vol(list(featmod._price_history)) == rms_price_vol(prices)

    nxt = featmod.build_features(
        {
            "ts": datetime.now(ZoneInfo("America/New_York")),
            "load_mw": 100_000.0,
            "rto_lmp": 40.0,
            "quality": 1.0,
            "zonal_lmps": {"BGE": 30.0},
        },
        None,
    )
    assert nxt.price_vol_missing is False
    assert nxt.price_vol == rms_price_vol(prices + [40.0])
