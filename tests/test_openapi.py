from pjm_nowcast.payments.routes import PAID_ROUTES, price_for

PAID = list(PAID_ROUTES)
FREE = ["/", "/health", "/v1/demo/sample", "/v1/discovery"]


def test_openapi_is_v3(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "pjm-nowcast"


def test_root_service_card_unchanged(client):
    card = client.get("/").json()
    spec = client.get("/openapi.json").json()
    assert card["name"] == "pjm-nowcast"
    assert "endpoints" in card
    assert spec["info"]["title"] == "pjm-nowcast"
    # card is not replaced by the OpenAPI document
    assert "openapi" not in card


def test_demo_sample_openapi_is_unpaid_fetch(client):
    spec = client.get("/openapi.json").json()
    get = spec["paths"]["/v1/demo/sample"]["get"]
    assert get.get("security") == []
    assert get["summary"] == "Fetch a synthetic unpaid nowcast sample fixture"
    assert 24 <= len(get["summary"]) <= 63
    assert "402" not in get.get("responses", {})
    assert "post" not in spec["paths"]["/v1/demo/sample"]


def test_free_routes_have_empty_security(client):
    spec = client.get("/openapi.json").json()
    for path in FREE:
        ops = spec["paths"][path]
        for verb, op in ops.items():
            if verb.lower() in {"get", "post", "put", "patch", "delete"}:
                assert op.get("security") == [], f"{verb.upper()} {path}"


def test_only_three_paid_nowcast_posts_have_payment_docs(client):
    spec = client.get("/openapi.json").json()
    paid_in_spec = [
        path
        for path, methods in spec["paths"].items()
        if isinstance(methods.get("post"), dict)
        and "x-payment-info" in methods["post"]
    ]
    assert sorted(paid_in_spec) == sorted(PAID)
    for path in PAID:
        post = spec["paths"][path]["post"]
        assert "402" in post["responses"]
        info = post["x-payment-info"]
        assert info["scheme"] == "exact"
        assert info["asset"] == "USDC"
        assert info["price"] == price_for(path, client.app.state.settings)
        assert info["facilitator"] == client.app.state.settings.facilitator_url
        from pjm_nowcast.payments.routes import public_network_names

        assert info["networks"] == public_network_names(client.app.state.settings)
        assert "accepts" not in info
        assert "resource" not in info


def test_mcp_not_in_openapi(client):
    spec = client.get("/openapi.json").json()
    mcp = client.app.state.settings.mcp_path
    assert mcp not in spec["paths"]
    assert f"{mcp}/" not in spec["paths"]


def test_openapi_catalog_omits_payto(client):
    spec = client.get("/openapi.json").json()
    dumped = str(spec)
    assert "payTo" not in dumped
    assert "pay_to" not in dumped
    for path in PAID:
        info = spec["paths"][path]["post"]["x-payment-info"]
        assert "accepts" not in info
        assert "payTo" not in str(info)
