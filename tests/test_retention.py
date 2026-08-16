from datetime import datetime, timedelta, timezone

from pjm_nowcast.db.store import Store


def test_prune_drops_old_rows_and_cascades(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    new = now - timedelta(hours=1)
    store.insert_observation(
        ts=old,
        fetched_at=old,
        load_mw=1.0,
        rto_lmp=1.0,
        published_peak_today_mw=None,
        published_peak_tomorrow_mw=None,
        quality=1.0,
        source="old",
        as_of_text=None,
        load_ramp_mw=None,
        zonals={"BGE": 1.0},
    )
    store.insert_observation(
        ts=new,
        fetched_at=new,
        load_mw=2.0,
        rto_lmp=2.0,
        published_peak_today_mw=None,
        published_peak_tomorrow_mw=None,
        quality=1.0,
        source="new",
        as_of_text=None,
        load_ramp_mw=None,
        zonals={"BGE": 2.0},
    )
    deleted = store.prune(30, now=now)
    assert deleted == 1
    assert store.count() == 1
    latest = store.latest()
    assert latest is not None
    assert latest.source == "new"
    store.close()
