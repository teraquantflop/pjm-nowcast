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


def test_empty_body_unpaid_is_402_not_400(enforcing_client):
    r = enforcing_client.post("/v1/nowcast/latest")
    assert r.status_code == 402, r.text
    assert "payment-required" in {k.lower() for k in r.headers.keys()}


def test_garbage_body_unpaid_is_402(enforcing_client):
    r = enforcing_client.post(
        "/v1/nowcast/history",
        content=b"not-json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 402
