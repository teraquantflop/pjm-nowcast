from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pjm_nowcast.db.store import Store, target_hour_ept
from pjm_nowcast.stats.assemble import assemble_latest, snapshot_record_from_latest
from tests.conftest import seed_observation

ET = ZoneInfo("America/New_York")


def test_append_dedup_no_mutation(tmp_path, settings):
    store = Store(tmp_path / "s.sqlite")
    asof = datetime(2026, 8, 19, 14, 20, tzinfo=ET)
    hour = target_hour_ept(asof)
    row = {
        "fetched_at_utc": asof.astimezone(timezone.utc).isoformat(),
        "asof": asof.isoformat(),
        "target_hour_ept": hour,
        "rto_nc": 33.0,
        "zone_nc": '{"BGE": 40.0}',
        "spr_nc": 5.0,
        "load_nc": 100000.0,
        "price_vol": 2.5,
        "price_vol_missing": False,
        "mix_std_price": 8.0,
        "mix_n_obs": 10,
    }
    assert store.insert_nowcast_snapshot(row) is True
    second = dict(row, rto_nc=99.0, fetched_at_utc=(asof + timedelta(minutes=20)).astimezone(timezone.utc).isoformat())
    assert store.insert_nowcast_snapshot(second) is False
    listed = store.list_nowcast_snapshots()
    assert len(listed) == 1
    assert listed[0]["rto_nc"] == 33.0
    assert listed[0]["target_hour_ept"] == hour
    store.close()


def test_zone_nc_null_when_missing(tmp_path):
    store = Store(tmp_path / "s2.sqlite")
    asof = datetime(2026, 8, 19, 15, 5, tzinfo=ET)
    row = {
        "fetched_at_utc": asof.astimezone(timezone.utc).isoformat(),
        "asof": asof.isoformat(),
        "target_hour_ept": target_hour_ept(asof),
        "rto_nc": 40.0,
        "zone_nc": None,
        "spr_nc": None,
        "load_nc": 90000.0,
        "price_vol": None,
        "price_vol_missing": True,
        "mix_std_price": None,
        "mix_n_obs": None,
    }
    assert store.insert_nowcast_snapshot(row) is True
    listed = store.list_nowcast_snapshots()
    assert listed[0]["zone_nc"] is None
    assert listed[0]["spr_nc"] is None
    store.close()


def test_poller_writes_snapshot(client, store, settings):
    seed_observation(store, hours_ago=0.1, rto_lmp=41.0)
    body = assemble_latest(store, settings)
    assert body is not None
    rec = snapshot_record_from_latest(body, datetime.now(timezone.utc))
    assert rec is not None
    assert rec["rto_nc"] == 41.0
    assert rec["target_hour_ept"]
    store.insert_nowcast_snapshot(rec)
    r = client.post("/v1/nowcast/snapshots", json={})
    assert r.status_code == 200
    payload = r.json()
    assert payload["count"] >= 1
    assert payload["windowDays"] == 90
    assert "not a forward forecast" in payload["disclaimer"].lower()
    assert payload["snapshots"][0]["rto_nc"] == 41.0


def test_snapshots_unpaid_402(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pjm_nowcast.api.app import create_app
    from pjm_nowcast.settings import Settings

    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "p.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post("/v1/nowcast/snapshots", json={})
        assert r.status_code == 402
        assert "payTo" not in r.text


def test_capabilities_mentions_snapshots(client):
    body = client.get("/v1/capabilities").json()
    assert body["windows"]["snapshotDays"] == 90
    assert "POST /v1/nowcast/snapshots" in body["prices"]


def test_llms_mentions_snapshots(client):
    text = client.get("/llms.txt").text
    assert "/v1/nowcast/snapshots" in text
    assert "90-day" in text or "90-day cap" in text
