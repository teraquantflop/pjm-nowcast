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
        assert info["networks"] == client.app.state.settings.network_list
        from pjm_nowcast.payments.routes import usdc_atomic_amount

        atomic = usdc_atomic_amount(info["price"])
        assert isinstance(info["resource"], dict)
        assert info["resource"]["url"].endswith(path)
        for acc in info["accepts"]:
            assert acc["amount"] == atomic
            assert acc["maxAmountRequired"] == atomic
            assert acc["maxTimeoutSeconds"] == 60
            assert acc["price"] == info["price"]
            assert acc["scheme"] == "exact"
            if acc["network"] == "eip155:8453":
                assert acc["asset"] == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                assert acc["extra"]["name"] == "USD Coin"
                assert acc["extra"]["version"] == "2"
            if acc["network"] == "eip155:137":
                assert acc["asset"] == "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
                assert acc["extra"]["name"] == "USD Coin"
                assert acc["extra"]["version"] == "2"


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
        accepts = spec["paths"][path]["post"]["x-payment-info"]["accepts"]
        for item in accepts:
            assert "payTo" not in item
            assert "pay_to" not in item
