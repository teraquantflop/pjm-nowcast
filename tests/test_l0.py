from tests.conftest import seed_observation


def test_health_empty(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "unavailable"
    assert r.json()["db"] == "ok"


def test_service_card(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "pjm-nowcast"
    assert "forecast" in body["whatItIsNot"].lower()
    assert "HMM" not in r.text
    assert "entropy" not in r.text.lower()
    paths = {e["path"] for e in body["endpoints"]}
    assert "/v1/nowcast/latest" in paths
    assert "/v1/nowcast/history" in paths
    assert "/v1/nowcast/history/extended" in paths


def test_discovery_alias(client):
    assert client.get("/v1/discovery").json()["name"] == "pjm-nowcast"


def test_demo_does_not_need_db(client, store):
    assert store.count() == 0
    r = client.get("/v1/demo/sample")
    assert r.status_code == 200
    assert r.json()["product"] == "pjm-nowcast"
    assert store.count() == 0


def test_health_ok_after_seed(client, store):
    seed_observation(store, hours_ago=0.1)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")
    assert r.json()["data"]["stale"] is False
