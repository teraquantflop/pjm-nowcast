from pjm_nowcast.payments.facilitators import build_facilitator_clients
from pjm_nowcast.settings import Settings


def test_missing_cdp_keys_still_builds_payai(tmp_path):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=True,
        data_dir=tmp_path,
        database_path=tmp_path / "f.sqlite",
        cdp_api_key_id="",
        cdp_api_key_secret="",
    )
    assert settings.cdp_configured is False
    status = settings.facilitator_status()
    assert status["payai"] is True
    assert status["cdp"] is False
    assert status["base"] == "payai"
    assert status["solana"] == "payai"
    assert status["polygon"] == "payai"
    clients = build_facilitator_clients(settings)
    assert len(clients) == 1


def test_partial_cdp_keys_ignored(tmp_path):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=True,
        data_dir=tmp_path,
        database_path=tmp_path / "f.sqlite",
        cdp_api_key_id="only-id",
        cdp_api_key_secret="",
    )
    assert settings.cdp_configured is False
    assert len(build_facilitator_clients(settings)) == 1


def test_cdp_keys_set_status_without_crashing(tmp_path, monkeypatch):
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=True,
        data_dir=tmp_path,
        database_path=tmp_path / "f.sqlite",
        cdp_api_key_id="test-id",
        cdp_api_key_secret="test-secret",
    )
    assert settings.cdp_configured is True
    status = settings.facilitator_status()
    assert status["cdp"] is True
    assert status["base"] == "cdp"
    assert status["solana"] == "payai"
    assert status["polygon"] == "payai"
    # Even if cdp-sdk is missing, PayAI client is still built.
    clients = build_facilitator_clients(settings)
    assert len(clients) >= 1


def test_health_and_root_list_facilitators(client):
    health = client.get("/health").json()
    card = client.get("/").json()
    for body in (health, card):
        fac = body["facilitators"]
        assert fac["payai"] is True
        assert "cdp" in fac
        assert fac["solana"] == "payai"
        assert fac["polygon"] == "payai"
        dumped = str(body)
        assert "test-secret" not in dumped
        assert "CDP_API_KEY_SECRET" not in dumped
