"""Background poller. The only component that talks to the public market page."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pjm_nowcast.db.store import Store
from pjm_nowcast.ingest.normalize import normalize
from pjm_nowcast.ingest.scraper import FetchError, fetch_page
from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast.poller")
ET = ZoneInfo("America/New_York")


def poll_once(
    store: Store,
    settings: Settings,
    retry_delays: tuple[float, ...] = (0, 5, 15, 45),
) -> int | None:
    """Fetch one observation. Returns observation id or None on failure."""
    started = datetime.now(timezone.utc)
    run_id = store.start_poll_run(started)
    last = store.latest()
    previous = None
    prev_load = None
    if last is not None:
        prev_load = last.load_mw
        previous = {
            "load_mw": last.load_mw,
            "rto_lmp": last.rto_lmp,
            "published_peak_today_mw": last.published_peak_today_mw,
            "published_peak_tomorrow_mw": last.published_peak_tomorrow_mw,
            "zonal_lmps": last.zonals,
            "quality": last.quality,
            "source": last.source,
            "as_of_text": last.as_of_text,
        }

    last_err: str | None = None
    for attempt, delay in enumerate(retry_delays):
        if delay:
            import time

            time.sleep(delay)
        try:
            raw = fetch_page(settings, previous=previous)
            row = normalize(raw, prev_load)
            oid = store.insert_observation(**row)
            store.prune(settings.retention_days)
            store.finish_poll_run(
                run_id,
                ok=True,
                finished_at=datetime.now(timezone.utc),
                observation_id=oid,
            )
            log.info("Poll wrote observation id=%s source=%s", oid, row["source"])
            return oid
        except FetchError as exc:
            last_err = str(exc)
            log.warning("Poll attempt %s failed: %s", attempt + 1, exc)
        except Exception as exc:
            last_err = str(exc)
            log.exception("Poll attempt %s crashed", attempt + 1)

    store.finish_poll_run(
        run_id,
        ok=False,
        finished_at=datetime.now(timezone.utc),
        error=last_err,
    )
    return None


async def run_poller(store: Store, settings: Settings, stop: asyncio.Event) -> None:
    """Supervised loop. Failures never kill the API process."""
    log.info(
        "Poller starting interval=%ss jitter=±%ss mock=%s",
        settings.poll_interval_seconds,
        settings.poll_jitter_seconds,
        settings.mock_mode,
    )
    while not stop.is_set():
        try:
            await asyncio.to_thread(poll_once, store, settings)
        except Exception:
            log.exception("Poller cycle crashed; API continues")
        base = max(60, int(settings.poll_interval_seconds))
        jitter = min(int(settings.poll_jitter_seconds), base // 2)
        sleep_for = base + random.uniform(-jitter, jitter)
        try:
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)
        except asyncio.TimeoutError:
            continue
    log.info("Poller stopped")
