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
    assert "When to use" in r.text
    assert "When not to use" in r.text
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
    body = r.json()
    assert body["product"] == "pjm-nowcast"
    assert body["demo"] is True
    assert body["synthetic"] is True
    assert str(body.get("asOf", "")).startswith("1900")
    assert str(body.get("requestId", "")).startswith("demo-")
    assert store.count() == 0


def test_demo_post_is_405_json(client):
    r = client.post("/v1/demo/sample", json={})
    assert r.status_code == 405
    allow = r.headers.get("allow") or r.headers.get("Allow") or ""
    assert "GET" in allow.upper()
    body = r.json()
    assert body["error"] == "method_not_allowed"
    assert "Do not POST /v1/demo/sample" in body["message"]
    assert body["allow"] == ["GET"]
    assert body["path"] == "/v1/demo/sample"


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
    llm = client.get("/llm.txt")
    wk_llms = client.get("/.well-known/llms.txt")
    wk_llm = client.get("/.well-known/llm.txt")
    robots = client.get("/robots.txt")
    wk = client.get("/.well-known/x402")
    wk_json = client.get("/.well-known/x402.json")
    assert llms.status_code == 200
    assert llm.status_code == 200
    assert llm.text == llms.text
    assert wk_llms.text == llms.text
    assert wk_llm.text == llms.text
    assert "/swagger.json" in llms.text
    assert "/mcp" in llms.text
    assert "price_vol" in llms.text
    assert "Streamable HTTP" in llms.text
    assert robots.status_code == 200
    assert "User-agent" in robots.text
    assert "Allow: /openapi.json" in robots.text
    assert "Allow: /llm.txt" in robots.text
    assert "Allow: /.well-known/" in robots.text
    assert "Disallow: /v1/" not in robots.text
    ctype = robots.headers.get("content-type", "")
    assert "text/plain" in ctype
    cache = robots.headers.get("cache-control", "")
    assert "max-age=3600" in cache
    assert "When to use" in llms.text
    assert "When not to use" in llms.text
    assert wk.status_code == 200
    assert wk_json.status_code == 200
    assert wk.json() == wk_json.json()
    assert "payToByNetwork" not in wk.json()
    assert "polygon" in wk.json()["networks"] or "solana" in wk.json()["networks"]
    assert wk.json()["mcp"]["url"].endswith("/mcp")
    card = client.get("/").json()
    paths = {e["path"] for e in card["endpoints"]}
    assert "/swagger.json" in paths
    assert "/skill.md" in paths
    assert "/llms.txt" in paths
    assert "/.well-known/x402" in paths
    assert "/mcp" in paths
    assert "/.well-known/agent.json" in paths
    assert "/.well-known/x402-resources" in paths
    assert "entropy" not in str(card).lower()
    agent = client.get("/.well-known/agent.json")
    assert agent.status_code == 200
    assert agent.json()["name"] == "pjm-nowcast"
    resources = client.get("/.well-known/x402-resources")
    assert resources.status_code == 200
    assert resources.json()["resources"]


def test_health_ok_after_seed(client, store):
    seed_observation(store, hours_ago=0.1)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")
    assert r.json()["data"]["stale"] is False
