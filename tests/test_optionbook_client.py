from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.payments.optionbook import header_matches
from pjm_nowcast.settings import Settings
from tests.conftest import seed_observation

_ID = "ob-test-id-aaaa"
_HEADER = "OptionBookClient"


@pytest.fixture
def ob_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        database_path=tmp_path / "ob.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        pay_to_svm_address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
        optionbook_id=_ID,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def ob_unset_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        database_path=tmp_path / "ob2.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
        optionbook_id="",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_header_matches_length_and_empty():
    assert header_matches("", "x") is False
    assert header_matches(None, "x") is False
    assert header_matches(_ID, None) is False
    assert header_matches(_ID, "") is False
    assert header_matches(_ID, _ID[:-1]) is False
    assert header_matches(_ID, _ID + "z") is False
    assert header_matches(_ID, "xxxxxxxxxxxxxxxx") is False
    assert header_matches(_ID, "ob-test-id-bbbb") is False
    assert header_matches(_ID, _ID) is True


def test_match_skips_x402(ob_client):
    seed_observation(ob_client.app.state.store)
    for path in (
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    ):
        r = ob_client.post(path, json={}, headers={_HEADER: _ID})
        assert r.status_code == 200, (path, r.status_code, r.text)


def test_mismatch_is_402(ob_client):
    r = ob_client.post(
        "/v1/nowcast/latest",
        json={},
        headers={_HEADER: "ob-test-id-bbbb"},
    )
    assert r.status_code == 402


def test_wrong_length_is_402(ob_client):
    r = ob_client.post("/v1/nowcast/latest", json={}, headers={_HEADER: "short"})
    assert r.status_code == 402


def test_unset_env_stays_402(ob_unset_client):
    r = ob_unset_client.post(
        "/v1/nowcast/latest",
        json={},
        headers={_HEADER: _ID},
    )
    assert r.status_code == 402


def test_health_unchanged(ob_client):
    r = ob_client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


def test_mcp_match_and_miss(ob_client):
    seed_observation(ob_client.app.state.store)
    miss = ob_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "nowcast_latest", "arguments": {}},
        },
    )
    assert miss.status_code == 200
    assert miss.json()["result"]["structuredContent"]["paymentStatus"] == "required"

    hit = ob_client.post(
        "/mcp",
        headers={_HEADER: _ID},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "nowcast_latest", "arguments": {}},
        },
    )
    assert hit.status_code == 200
    result = hit.json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["paymentStatus"] == "paid"


def test_match_log_is_boolean_only(ob_client, caplog):
    seed_observation(ob_client.app.state.store)
    with caplog.at_level("INFO"):
        r = ob_client.post(
            "/v1/nowcast/latest",
            json={},
            headers={_HEADER: _ID},
        )
    assert r.status_code == 200
    text = caplog.text
    assert "optionbook_client=True" in text
    assert _ID not in text
