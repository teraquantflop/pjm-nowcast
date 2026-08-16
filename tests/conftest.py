from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Defaults before settings are constructed
os.environ.setdefault("ENV", "test")
os.environ.setdefault("RUN_POLLER", "false")
os.environ.setdefault("X402_DISABLED", "true")
os.environ.setdefault("MCP_ENABLED", "true")
os.environ.setdefault("FREE_DEMO_ENABLED", "true")
os.environ.setdefault("RATE_LIMIT_RPS", "1000")
os.environ.setdefault("RATE_LIMIT_BURST", "1000")


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "true")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    from pjm_nowcast.settings import Settings, reset_settings_cache

    reset_settings_cache()
    return Settings()


@pytest.fixture
def app(settings):
    from pjm_nowcast.api.app import create_app

    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def store(app):
    return app.state.store


def seed_observation(store, *, hours_ago: float = 0.0, **overrides):
    now = datetime.now(timezone.utc)
    ts = now - timedelta(hours=hours_ago)
    fields = {
        "ts": ts,
        "fetched_at": ts,
        "load_mw": 100000.0,
        "rto_lmp": 30.0,
        "published_peak_today_mw": 120000.0,
        "published_peak_tomorrow_mw": 118000.0,
        "quality": 1.0,
        "source": "test",
        "as_of_text": None,
        "load_ramp_mw": 100.0,
        "zonals": {
            "BGE": 32.0,
            "COMED": 25.0,
            "DOM": 31.0,
            "PEPCO": 33.0,
            "PSEG": 30.0,
            "JCPL": 29.0,
        },
    }
    fields.update(overrides)
    return store.insert_observation(**fields)
