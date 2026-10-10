from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import Settings


@pytest.fixture
def enforcing_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "pay.sqlite"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("PAY_TO_EVM_ADDRESS", "0x1111111111111111111111111111111111111111")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    settings = Settings()
    assert settings.x402_disabled is False
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _challenge(resp):
    import base64
    import json

    raw = resp.headers.get("payment-required") or resp.headers.get("PAYMENT-REQUIRED")
    assert raw, resp.headers
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def test_empty_body_unpaid_is_402_not_400(enforcing_client):
    r = enforcing_client.post("/v1/nowcast/latest")
    assert r.status_code == 402, r.text
    assert "payment-required" in {k.lower() for k in r.headers.keys()}


def test_empty_json_object_is_402_with_atomic_amounts(enforcing_client):
    expected = {
        "/v1/nowcast/latest": "20000",
        "/v1/nowcast/history": "100000",
        "/v1/nowcast/history/extended": "250000",
    }
    prices = {
        "/v1/nowcast/latest": "$0.02",
        "/v1/nowcast/history": "$0.10",
        "/v1/nowcast/history/extended": "$0.25",
    }
    for path, atomic in expected.items():
        r = enforcing_client.post(path, json={})
        assert r.status_code == 402, path
        challenge = _challenge(r)
        body = r.json()
        assert body["error"] == "payment_required"
        assert body["path"] == path
        assert "accepts" not in body
        assert "payTo" not in str(body)
        assert challenge["accepts"]
        assert challenge["x402Version"] == 2
        assert isinstance(challenge["resource"], dict)
        assert challenge["resource"]["url"] == f"http://testserver{path}"
        assert challenge["resource"].get("description")
        for acc in challenge["accepts"]:
            assert acc["scheme"] == "exact"
            assert acc["amount"] == atomic
            assert acc["maxAmountRequired"] == atomic
            assert acc["maxTimeoutSeconds"] == 60
            assert acc["price"] == prices[path]
            assert acc["network"]
            assert acc["payTo"]
            if acc["network"] == "eip155:8453":
                assert acc["asset"] == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                assert acc["extra"] == {"name": "USD Coin", "version": "2"}
            elif acc["network"] == "eip155:137":
                assert acc["asset"] == "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
                assert acc["extra"] == {"name": "USD Coin", "version": "2"}
            else:
                assert acc["asset"] == "USDC"


def test_garbage_body_unpaid_is_402(enforcing_client):
    r = enforcing_client.post(
        "/v1/nowcast/history",
        content=b"not-json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 402
    _challenge(r)


def test_get_on_paid_path_is_402_not_405(enforcing_client):
    for path in (
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    ):
        r = enforcing_client.get(path)
        assert r.status_code == 402, path
        assert r.status_code != 200
        acc = _challenge(r)["accepts"][0]
        assert acc["amount"]
        assert acc["maxAmountRequired"] == acc["amount"]
        assert "rtoLmp" not in r.json()


def test_head_on_paid_path_is_402(enforcing_client):
    for path in (
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    ):
        r = enforcing_client.head(path)
        assert r.status_code == 402, path
        allow = r.headers.get("allow") or r.headers.get("Allow") or ""
        assert "POST" in allow.upper()
        raw = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
        assert raw, path
        challenge = _challenge(r)
        assert challenge["accepts"]
        body = r.json() if r.content else {}
        assert "rtoLmp" not in body


def test_unpaid_probes_do_not_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1")
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "rl.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1,
        rate_limit_burst=1,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        for path in (
            "/v1/nowcast/latest",
            "/v1/nowcast/history",
            "/v1/nowcast/history/extended",
        ):
            for _ in range(5):
                r = c.post(path, json={})
                assert r.status_code == 402, path
                r_get = c.get(path)
                assert r_get.status_code == 402, path


NOWCAST_BAZAAR_INPUTS = {
    "/v1/nowcast/latest": {},
    "/v1/nowcast/history": {"hours": 24},
    "/v1/nowcast/history/extended": {"hours": 168},
    "/v1/nowcast/regime": {},
    "/v1/nowcast/spreads": {},
    "/v1/nowcast/asof": {"asof": "2026-10-09T18:00:00-04:00"},
    "/v1/nowcast/snapshots": {
        "from": "2026-10-09T00:00:00-04:00",
        "to": "2026-10-10T00:00:00-04:00",
    },
}


def test_unpaid_nowcast_402_has_bazaar_input_and_output(enforcing_client):
    from pjm_nowcast.payments.routes import PAID_DESCRIPTIONS
    from pjm_nowcast.spread_card import SPREAD_CARD_PATH

    for path, body in NOWCAST_BAZAAR_INPUTS.items():
        r = enforcing_client.post(path, json={})
        assert r.status_code == 402, path
        challenge = _challenge(r)
        assert challenge["resource"].get("description") == PAID_DESCRIPTIONS[path]
        info = (challenge.get("extensions") or {}).get("bazaar", {}).get("info") or {}
        assert "input" in info, path
        assert "output" in info, path
        assert (challenge["extensions"]["bazaar"].get("schema")), path
        assert info["input"].get("body") == body, path
        example = info["output"].get("example") or {}
        if path == "/v1/nowcast/snapshots":
            assert "asof" in (example.get("snapshots") or [{}])[0]
            assert "no stored nowcast" in example["disclaimer"]
            assert "ageSeconds" not in example
        else:
            assert "asOf" in example, path
            assert "ageSeconds" in example, path
        if path == "/v1/nowcast/regime":
            assert "entropy" in example
            assert "posteriors" in example
            assert "kStar" in example
        if path == "/v1/nowcast/spreads":
            assert "zones" in example
            assert "points" not in example

    card = enforcing_client.post(SPREAD_CARD_PATH, json={})
    assert card.status_code == 402
    card_ch = _challenge(card)
    card_info = card_ch["extensions"]["bazaar"]["info"]
    assert "input" in card_info
    assert "output" in card_info
    assert card_info["input"]["body"] == {"lookbackDays": 5}


def _bazaar_schema(resp) -> dict:
    challenge = _challenge(resp)
    schema = (challenge.get("extensions") or {}).get("bazaar", {}).get("schema")
    assert isinstance(schema, dict), challenge
    assert "properties" in schema
    return schema


def test_unpaid_402_bazaar_has_input_schema(enforcing_client):
    from pjm_nowcast.spread_card import SPREAD_CARD_PATH

    empty_paths = (
        "/v1/nowcast/latest",
        "/v1/nowcast/regime",
        "/v1/nowcast/spreads",
    )
    for path in empty_paths:
        r = enforcing_client.post(path, json={})
        assert r.status_code == 402, path
        schema = _bazaar_schema(r)
        assert schema.get("type") == "object"
        assert isinstance(schema["properties"], dict)
        assert schema.get("required") in (None, [])

    asof = enforcing_client.post("/v1/nowcast/asof", json={})
    assert asof.status_code == 402
    asof_schema = _bazaar_schema(asof)
    assert asof_schema["required"] == ["asof"]
    assert asof_schema["properties"]["asof"]["type"] == "string"

    snaps = enforcing_client.post("/v1/nowcast/snapshots", json={})
    assert snaps.status_code == 402
    snap_schema = _bazaar_schema(snaps)
    assert snap_schema["required"] == ["from", "to"]
    assert snap_schema["properties"]["from"]["type"] == "string"
    assert snap_schema["properties"]["to"]["type"] == "string"

    card = enforcing_client.post(SPREAD_CARD_PATH, json={})
    assert card.status_code == 402
    card_schema = _bazaar_schema(card)
    assert card_schema["required"] == ["lookbackDays"]
    assert card_schema["properties"]["lookbackDays"]["type"] == "integer"

    history = enforcing_client.post("/v1/nowcast/history", json={})
    assert history.status_code == 402
    hist_schema = _bazaar_schema(history)
    assert hist_schema["properties"]["windowHours"]["type"] == "integer"
    assert hist_schema.get("required") in (None, [])

    extended = enforcing_client.post("/v1/nowcast/history/extended", json={})
    assert extended.status_code == 402
    ext_schema = _bazaar_schema(extended)
    assert ext_schema["properties"]["windowHours"]["type"] == "integer"
    assert ext_schema.get("required") in (None, [])
