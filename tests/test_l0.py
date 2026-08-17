from tests.conftest import seed_observation


def test_health_empty(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "unavailable"
    assert r.json()["db"] == "ok"
    assert r.json()["facilitators"]["payai"] is True


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


def test_favicon_ico(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.content
    ctype = r.headers.get("content-type", "")
    assert "icon" in ctype or "octet-stream" in ctype


def test_favicon_png_and_svg(client):
    png = client.get("/favicon.png")
    assert png.status_code == 200
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    svg = client.get("/favicon.svg")
    assert svg.status_code == 200
    assert b"<svg" in svg.content


def test_service_card_icon_url_defaults_to_favicon(client):
    card = client.get("/").json()
    assert card["iconUrl"].endswith("/favicon.ico")


def test_health_ok_after_seed(client, store):
    seed_observation(store, hours_ago=0.1)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")
    assert r.json()["data"]["stale"] is False
