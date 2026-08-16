from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import Settings
from tests.conftest import seed_observation


def test_same_key_same_body_cached(tmp_path: Path):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "i.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    seed_observation(app.state.store)
    body = b"{}"
    app.state.store.put_idempotency(
        "abc-1",
        "/v1/nowcast/latest",
        hashlib.sha256(body).hexdigest(),
        200,
        json.dumps({"cached": True, "asOf": "seeded"}),
        datetime.now(timezone.utc),
    )
    with TestClient(app) as c:
        r = c.post(
            "/v1/nowcast/latest",
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": "abc-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["cached"] is True


def test_same_key_different_body_409(tmp_path: Path):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "i2.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    seed_observation(app.state.store)
    app.state.store.put_idempotency(
        "abc-2",
        "/v1/nowcast/latest",
        hashlib.sha256(b'{"families":["rto_lmp"]}').hexdigest(),
        200,
        json.dumps({"ok": True}),
        datetime.now(timezone.utc),
    )
    with TestClient(app) as c:
        r = c.post(
            "/v1/nowcast/latest",
            json={"families": ["rto_load"]},
            headers={"Idempotency-Key": "abc-2"},
        )
        assert r.status_code == 409
