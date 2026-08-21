from __future__ import annotations

import json
from pathlib import Path

from pjm_nowcast.stats.assemble import assemble_latest
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
