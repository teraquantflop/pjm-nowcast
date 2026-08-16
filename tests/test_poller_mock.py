from pjm_nowcast.poller.job import poll_once
from pjm_nowcast.settings import Settings


def test_mock_poll_writes_row(tmp_path, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    settings = Settings(
        mock_mode=True,
        run_poller=False,
        database_path=tmp_path / "p.sqlite",
        data_dir=tmp_path,
        env="test",
        x402_disabled=True,
    )
    from pjm_nowcast.db.store import Store

    store = Store(settings.database_path)
    oid = poll_once(store, settings)
    assert oid is not None
    assert store.count() == 1
    latest = store.latest()
    assert latest is not None
    assert latest.source == "mock"
    assert latest.load_mw != 85000 or latest.rto_lmp != 25.0
    store.close()


def test_failed_fetch_does_not_write_placeholder(tmp_path, monkeypatch):
    from pjm_nowcast.db.store import Store
    from pjm_nowcast.ingest import scraper

    settings = Settings(
        mock_mode=False,
        poll_carry_forward=False,
        run_poller=False,
        database_path=tmp_path / "p.sqlite",
        data_dir=tmp_path,
        env="test",
        x402_disabled=True,
        poll_url="http://127.0.0.1:1/does-not-exist",
        request_timeout_sec=0.2,
    )
    store = Store(settings.database_path)

    def boom(*_a, **_k):
        raise scraper.FetchError("nope")

    monkeypatch.setattr(scraper, "fetch_page", boom)
    # poll_once imports fetch_page at call time from the module; patch the name used in job
    import pjm_nowcast.poller.job as job

    monkeypatch.setattr(job, "fetch_page", boom)
    oid = poll_once(store, settings, retry_delays=(0,))
    assert oid is None
    assert store.count() == 0
    store.close()
