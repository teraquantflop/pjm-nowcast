from tests.conftest import seed_observation


def test_l2_rejects_73h(client, store):
    seed_observation(store)
    r = client.post("/v1/nowcast/history", json={"windowHours": 73})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_l2_accepts_72h(client, store):
    seed_observation(store, hours_ago=1)
    r = client.post("/v1/nowcast/history", json={"windowHours": 72})
    assert r.status_code == 200
    assert "points" in r.json()["rtoLmp"]


def test_l3_rejects_above_max(client, store):
    seed_observation(store)
    r = client.post(
        "/v1/nowcast/history/extended",
        json={"windowHours": 30 * 24 + 1},
    )
    assert r.status_code == 400


def test_l3_compare_prior(client, store):
    for h in range(0, 10):
        seed_observation(store, hours_ago=h, rto_lmp=20 + h)
    r = client.post(
        "/v1/nowcast/history/extended",
        json={"windowHours": 4, "compare": "prior_period", "resolution": "hourly"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "priorPeriod" in body
    assert body["resolution"] == "hourly"
