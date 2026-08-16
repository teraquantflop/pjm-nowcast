from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import Settings
from tests.conftest import seed_observation


def test_first_n_free_then_402(tmp_path: Path):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "f.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        free_tier_n=1,
        free_tier_window_seconds=86400,
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    seed_observation(app.state.store)
    with TestClient(app) as c:
        r1 = c.post("/v1/nowcast/latest", json={})
        assert r1.status_code == 200
        r2 = c.post("/v1/nowcast/latest", json={})
        assert r2.status_code == 402
