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


def test_swagger_matches_openapi(client):
    swagger = client.get("/swagger.json")
    openapi = client.get("/openapi.json")
    assert swagger.status_code == 200
    assert openapi.status_code == 200
    assert swagger.json() == openapi.json()


def test_skill_md_aliases(client):
    lower = client.get("/skill.md")
    upper = client.get("/SKILL.md")
    assert lower.status_code == 200
    assert upper.status_code == 200
    assert lower.text == upper.text
    assert "PJM RTO nowcast" in lower.text
    assert "/openapi.json" in lower.text
    assert "PAYMENT-REQUIRED" in lower.text
    assert "payTo" not in lower.text
    assert client.app.state.settings.price_l1 in lower.text


def test_llms_robots_well_known(client):
    llms = client.get("/llms.txt")
    robots = client.get("/robots.txt")
    wk = client.get("/.well-known/x402")
    wk_json = client.get("/.well-known/x402.json")
    assert llms.status_code == 200
    assert "/swagger.json" in llms.text
    assert robots.status_code == 200
    assert "Allow: /openapi.json" in robots.text
    assert wk.status_code == 200
    assert wk_json.status_code == 200
    assert wk.json() == wk_json.json()
    assert "payTo" not in wk.text
    card = client.get("/").json()
    paths = {e["path"] for e in card["endpoints"]}
    assert "/swagger.json" in paths
    assert "/skill.md" in paths
    assert "/llms.txt" in paths
    assert "/.well-known/x402" in paths


def test_health_ok_after_seed(client, store):
    seed_observation(store, hours_ago=0.1)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")
    assert r.json()["data"]["stale"] is False
