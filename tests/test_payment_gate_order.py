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
        assert body["accepts"]
        assert challenge["accepts"] == body["accepts"]
        assert challenge["x402Version"] == 2
        assert isinstance(challenge["resource"], dict)
        assert challenge["resource"]["url"] == f"http://testserver{path}"
        assert challenge["resource"].get("description")
        for acc in challenge["accepts"]:
            assert acc["scheme"] == "exact"
            assert acc["asset"] == "USDC"
            assert acc["amount"] == atomic
            assert acc["maxAmountRequired"] == atomic
            assert acc["maxTimeoutSeconds"] == 60
            assert acc["price"] == prices[path]
            assert acc["network"]
            assert acc["payTo"]


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
        acc = _challenge(r)["accepts"][0]
        assert acc["amount"]
        assert acc["maxAmountRequired"] == acc["amount"]


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
