from datetime import datetime, timedelta, timezone

from tests.conftest import seed_observation


def test_empty_store_503(client):
    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 503
    assert r.json()["error"] == "data_unavailable"


def test_fresh_not_stale(client, store):
    seed_observation(store, hours_ago=0.1)
    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is False
    assert "rtoLmp" in body
    assert "zonalSpread" in body
    assert "rtoLoad" in body
    assert body["rtoLoad"]["sourcePublishedPeakTodayMw"] == 120000.0


def test_old_row_stale_true(client, store):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    seed_observation(store, ts=old, fetched_at=old)
    r = client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 200
    assert r.json()["stale"] is True
    assert r.json()["ageSeconds"] > 10800
