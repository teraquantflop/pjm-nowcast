"""Free JSON/docs omit wallets. 402 header still carries payTo for x402 buyers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import Settings

EVM = "0x1111111111111111111111111111111111111111"
SVM = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
POLY = "0x2222222222222222222222222222222222222222"

_WALLET_SHAPED = re.compile(r"0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,}")


@pytest.fixture
def walleted_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("PAY_TO_EVM_ADDRESS", EVM)
    monkeypatch.setenv("PAY_TO_SVM_ADDRESS", SVM)
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "w.sqlite",
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


def _assert_no_wallets(text: str) -> None:
    assert _WALLET_SHAPED.search(text) is None, text[:500]
    lower = text.lower()
    assert "payto" not in lower.replace("_", "")
    assert EVM.lower() not in lower
    assert SVM not in text
    assert POLY.lower() not in lower


def test_free_routes_have_no_wallet_shaped_strings(walleted_client):
    for path in (
        "/health",
        "/",
        "/v1/discovery",
        "/openapi.json",
        "/swagger.json",
        "/skill.md",
        "/llms.txt",
        "/llm.txt",
        "/.well-known/x402",
        "/.well-known/x402.json",
        "/.well-known/agent.json",
        "/.well-known/x402-resources",
        "/.well-known/llms.txt",
        "/.well-known/llm.txt",
        "/v1/demo/sample",
        "/mcp",
    ):
        r = walleted_client.get(path)
        assert r.status_code == 200, path
        _assert_no_wallets(r.text)


def test_unpaid_402_header_has_payto_body_does_not(walleted_client):
    import base64
    import json

    for path in (
        "/v1/nowcast/latest",
        "/v1/nowcast/history",
        "/v1/nowcast/history/extended",
    ):
        r = walleted_client.post(path, json={})
        assert r.status_code == 402, path
        _assert_no_wallets(r.text)
        raw = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
        challenge = json.loads(base64.b64decode(raw).decode("utf-8"))
        paytos = {a.get("payTo") for a in challenge["accepts"]}
        assert EVM in paytos
        assert SVM in paytos
        assert POLY in paytos
        body = r.json()
        assert body["error"] == "payment_required"
        assert body["path"] == path
        assert body["method"] == "POST"
