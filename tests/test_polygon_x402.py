from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.payments.routes import (
    BASE_NETWORK,
    BASE_USDC_ADDRESS,
    POLYGON_NETWORK,
    POLYGON_USDC_ADDRESS,
    SOLANA_NETWORK,
    pay_to_by_network,
)
from pjm_nowcast.settings import Settings

EVM = "0x1111111111111111111111111111111111111111"
POLY = "0x2222222222222222222222222222222222222222"
SVM = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


@pytest.fixture
def poly_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "poly.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address=EVM,
        pay_to_svm_address=SVM,
        poly_pay_to=POLY,
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _challenge(resp):
    raw = resp.headers.get("payment-required") or resp.headers.get("PAYMENT-REQUIRED")
    assert raw, resp.headers
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def test_poly_pay_to_never_aliases_evm():
    s = Settings(
        env="test",
        run_poller=False,
        x402_disabled=True,
        pay_to_evm_address=EVM,
        poly_pay_to="",
        networks=f"{SOLANA_NETWORK},{BASE_NETWORK},{POLYGON_NETWORK}",
    )
    mapping = pay_to_by_network(s)
    assert mapping.get(BASE_NETWORK) == EVM
    assert POLYGON_NETWORK not in mapping
    s2 = Settings(
        env="test",
        run_poller=False,
        x402_disabled=True,
        pay_to_evm_address=EVM,
        poly_pay_to=POLY,
        networks=f"{SOLANA_NETWORK},{BASE_NETWORK},{POLYGON_NETWORK}",
    )
    mapping2 = pay_to_by_network(s2)
    assert mapping2[BASE_NETWORK] == EVM
    assert mapping2[POLYGON_NETWORK] == POLY
    assert mapping2[BASE_NETWORK] != mapping2[POLYGON_NETWORK]


def test_unpaid_402_lists_polygon_with_poly_pay_to(poly_client):
    r = poly_client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 402
    challenge = _challenge(r)
    by_net = {a["network"]: a for a in challenge["accepts"]}
    assert set(by_net) >= {SOLANA_NETWORK, BASE_NETWORK, POLYGON_NETWORK}

    sol = by_net[SOLANA_NETWORK]
    assert sol["payTo"] == SVM
    assert sol["scheme"] == "exact"
    assert sol["asset"] == "USDC"
    assert sol["amount"] == "20000"

    base = by_net[BASE_NETWORK]
    assert base["payTo"] == EVM
    assert base["asset"] == BASE_USDC_ADDRESS
    assert base["extra"] == {"name": "USD Coin", "version": "2"}

    poly = by_net[POLYGON_NETWORK]
    assert poly["payTo"] == POLY
    assert poly["payTo"] != EVM
    assert poly["scheme"] == "exact"
    assert poly["asset"] == POLYGON_USDC_ADDRESS
    assert poly["extra"] == {"name": "USD Coin", "version": "2"}
    assert poly["amount"] == "20000"
    assert poly["maxAmountRequired"] == "20000"


def test_health_lists_polygon(poly_client):
    health = poly_client.get("/health").json()
    assert health["facilitators"]["polygon"] == "payai"
    assert health["facilitators"]["solana"] == "payai"
    assert POLYGON_NETWORK in health["networks"]
    assert health["payToByNetwork"][POLYGON_NETWORK] == POLY
    assert health["payToByNetwork"][BASE_NETWORK] == EVM
    assert health["payToByNetwork"][SOLANA_NETWORK] == SVM


def test_well_known_agent_and_resources(poly_client):
    agent = poly_client.get("/.well-known/agent.json")
    assert agent.status_code == 200
    body = agent.json()
    assert body["name"] == "pjm-nowcast"
    assert body["version"]
    assert body["url"] == "http://testserver"
    assert body["facilitator"]
    assert POLYGON_NETWORK in body["networks"]
    assert body["payToByNetwork"][POLYGON_NETWORK] == POLY
    names = {t["name"] for t in body["tools"]}
    assert "nowcast_latest" in names
    paid = [t for t in body["tools"] if t.get("paid")]
    assert {t["path"] for t in paid} == {
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    }

    res = poly_client.get("/.well-known/x402-resources")
    assert res.status_code == 200
    payload = res.json()
    paths = {r["path"] for r in payload["resources"]}
    assert paths == {
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    }
    latest = next(r for r in payload["resources"] if r["path"] == "/v1/nowcast/latest")
    assert latest["method"] == "POST"
    assert latest["price"] == "$0.02"
    assert latest["scheme"] == "exact"
    assert POLYGON_NETWORK in latest["networks"]
    assert latest["payToByNetwork"][POLYGON_NETWORK] == POLY
    assert "inputSchema" in latest

    wk = poly_client.get("/.well-known/x402")
    assert wk.status_code == 200
    assert wk.json()["payToByNetwork"][POLYGON_NETWORK] == POLY


def test_root_and_mcp_advertise_polygon(poly_client):
    card = poly_client.get("/").json()
    assert POLYGON_NETWORK in card["networks"]
    assert card["payToByNetwork"][POLYGON_NETWORK] == POLY
    listed = poly_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert listed.status_code == 200
    tools = {t["name"]: t for t in listed.json()["result"]["tools"]}
    meta = tools["nowcast_latest"]["_meta"]["x402"]
    assert POLYGON_NETWORK in meta["networks"]
    assert meta["payToByNetwork"][POLYGON_NETWORK] == POLY
    assert meta["payToByNetwork"][BASE_NETWORK] == EVM
    assert meta["payToByNetwork"][SOLANA_NETWORK] == SVM
