from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.conftest import seed_observation


def test_access_log_and_request_id(client, caplog):
    caplog.set_level("INFO", logger="pjm_nowcast.access")
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("x-request-id") or r.headers.get("X-Request-Id")
    lines = [rec.message for rec in caplog.records if rec.name == "pjm_nowcast.access"]
    assert lines
    payload = json.loads(lines[-1])
    assert payload["path"] == "/health"
    assert payload["status"] == 200
    assert payload["payment"] == "free"
    assert payload["requestId"]
    assert "network" in payload


def test_head_discovery_200(client):
    for path in ("/", "/health", "/.well-known/x402"):
        r = client.head(path)
        assert r.status_code == 200, path


def test_capabilities_200(client):
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["windows"]["historyHoursMax"] == 72
    assert "price_vol" in body["fields"]
    assert "mix_std_price" in body["fields"]
    assert "solana" in body["networks"] or body["networks"]
    assert body["notAForecast"] is True
    assert "mark" in body["jobTags"]


def test_regime_spreads_when_x402_disabled(client, store, settings):
    seed_observation(store, hours_ago=0.1, rto_lmp=40.0)
    snap = Path(settings.snapshot_path)
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(
        json.dumps(
            {
                "last_entropy": 1.1,
                "state_posteriors": [0.1, 0.2, 0.1, 0.1, 0.5],
                "notes": "k*=4",
            }
        ),
        encoding="utf-8",
    )
    regime = client.post("/v1/nowcast/regime", json={})
    assert regime.status_code == 200
    body = regime.json()
    assert body["entropy"] == 1.1
    assert body["kStar"] == 4
    assert abs(sum(body["posteriors"]) - 1.0) < 1e-6
    assert "ageSeconds" in body
    assert "emission_mean" not in body

    spreads = client.post("/v1/nowcast/spreads", json={})
    assert spreads.status_code == 200
    sbody = spreads.json()
    assert "zones" in sbody
    assert "lastSpread" in sbody
    assert "points" not in sbody


def test_asof_fail_closed_and_hit(client, store):
    missing = client.post("/v1/nowcast/asof", json={})
    assert missing.status_code == 400
    bad = client.post("/v1/nowcast/asof", json={"asOf": "not-a-date"})
    assert bad.status_code == 400
    none = client.post("/v1/nowcast/asof", json={"asOf": "1990-01-01T00:00:00Z"})
    assert none.status_code in (404, 503)
    seed_observation(store, hours_ago=1.0, rto_lmp=33.0)
    now = datetime.now(timezone.utc)
    hit = client.post(
        "/v1/nowcast/asof",
        json={"asOf": (now + timedelta(minutes=1)).isoformat()},
    )
    assert hit.status_code == 200
    assert hit.json()["rtoLmp"]["last"] == 33.0


def test_new_paid_routes_402_when_enforced(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pjm_nowcast.api.app import create_app
    from pjm_nowcast.settings import Settings

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
        database_path=tmp_path / "p.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        for path in (
            "/v1/nowcast/regime",
            "/v1/nowcast/spreads",
            "/v1/nowcast/asof",
        ):
            r = c.post(path, json={})
            assert r.status_code == 402, path
            assert r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
            assert "payTo" not in r.text


def test_mcp_406_on_bad_accept(client):
    r = client.get("/mcp", headers={"Accept": "text/html"})
    assert r.status_code == 406
    body = r.json()
    assert "application/json" in body["message"]
    assert "text/event-stream" in body["message"]
