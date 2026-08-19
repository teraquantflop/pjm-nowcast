from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import Settings
from tests.conftest import seed_observation

EXPECTED_TOOLS = {
    "health",
    "service_info",
    "demo_sample",
    "nowcast_latest",
    "nowcast_history",
    "nowcast_history_extended",
}


def test_mcp_service_info_free(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == EXPECTED_TOOLS
    dumped = str(tools)
    assert "payTo" not in dumped
    assert "pay_to" not in dumped
    paid = {t["name"]: t for t in tools if t["name"].startswith("nowcast_")}
    for name, tool in paid.items():
        x402 = tool["_meta"]["x402"]
        assert x402["scheme"] == "exact"
        assert x402["asset"] == "USDC"
        assert x402["price"].startswith("$")
        assert "solana:" in "".join(x402["networks"])
        assert x402["httpPath"].startswith("/v1/nowcast/")
        assert "families" in tool["inputSchema"]["properties"]
        assert "required" not in tool["inputSchema"] or tool["inputSchema"]["required"] == []


def test_mcp_get_discover(client):
    r = client.get("/mcp")
    assert r.status_code == 200
    body = r.json()
    assert body["transport"] == "streamable-http"
    assert body["url"].endswith("/mcp")
    assert "tools/list" in body["note"] or "tools/list" in str(body["methods"])


def test_mcp_health_and_info(client, store):
    seed_observation(store)
    health = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "health", "arguments": {}},
        },
    )
    assert health.status_code == 200
    h = health.json()["result"]
    assert h["isError"] is False
    assert h["structuredContent"]["paymentStatus"] == "free"
    assert h["structuredContent"]["status"] in ("ok", "degraded")

    info = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "service_info", "arguments": {}},
        },
    )
    assert info.status_code == 200
    card = info.json()["result"]["structuredContent"]
    assert card["paymentStatus"] == "free"
    assert card["mcp"]["url"].endswith("/mcp")
    assert card["mcp"]["transport"] == "streamable-http"


def test_mcp_demo_and_latest(client, store):
    seed_observation(store)
    latest = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nowcast_latest", "arguments": {}},
        },
    )
    assert latest.status_code == 200
    # X402_DISABLED=true in default tests so the tool runs
    result = latest.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["paymentStatus"] == "paid"


@pytest.fixture
def paid_mcp_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        database_path=tmp_path / "m.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        pay_to_svm_address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_mcp_unpaid_paid_tool_surfaces_402_body(paid_mcp_client):
    r = paid_mcp_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "nowcast_latest", "arguments": {}},
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is True
    body = result["structuredContent"]
    assert body["paymentStatus"] == "required"
    assert body["error"] == "Payment required"
    assert "paymentRequired" in body
    accepts = body["paymentRequired"]["accepts"]
    assert accepts
    assert all(a["scheme"] == "exact" for a in accepts)


def test_http_paid_still_402(paid_mcp_client):
    r = paid_mcp_client.post("/v1/nowcast/latest", json={})
    assert r.status_code == 402
