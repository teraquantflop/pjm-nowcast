"""Background poller. The only component that talks to the public market page."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pjm_nowcast.db.store import Store
from pjm_nowcast.ingest.normalize import normalize
from pjm_nowcast.ingest.scraper import FetchError, fetch_page
from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast.poller")
ET = ZoneInfo("America/New_York")


def want_hmm_reset(settings: Settings, argv: list[str] | None = None) -> bool:
    argv = sys.argv if argv is None else argv
    if "--reset-hmm" in argv:
        return True
    return bool(settings.pjm_nowcast_reset_hmm)


def _hydrate_price_vol_window(
    store: Store, *, exclude_id: int | None = None
) -> tuple[int, float | None]:
    """Rebuild the in-memory LMP deque from SQLite (oldest first).

    When exclude_id is the row just inserted, build_features will append that
    print so the window is last-8 including current without doubling it.
    """
    from pjm_nowcast.ingest.features import restore_price_history
    from pjm_nowcast.stats.price_vol import PRICE_VOL_WINDOW, rms_price_vol

    lmps = store.recent_rto_lmps(PRICE_VOL_WINDOW, exclude_id=exclude_id)
    n_win = restore_price_history(lmps)
    return n_win, rms_price_vol(lmps)


def _hmm_tick(
    settings: Settings,
    snap,
    row: dict,
    store: Store | None = None,
    *,
    exclude_id: int | None = None,
) -> None:
    from pjm_nowcast.ingest.features import build_features
    from pjm_nowcast.model.hmm import predictive_summary, update
    from pjm_nowcast.model.persistence import save_snapshot

    if store is not None:
        prior_n, prior_vol = _hydrate_price_vol_window(store, exclude_id=exclude_id)
        log.info(
            "Hydrated LMP vol window from sqlite db=%s n_store=%s prior_n=%s prior_price_vol=%s",
            settings.database_path,
            store.count(),
            prior_n,
            f"{prior_vol:.4f}" if prior_vol is not None else "n/a",
        )
    feats = build_features(row, snap.last_features)
    update(snap, feats)
    save_snapshot(Path(settings.snapshot_path), snap)
    summary = predictive_summary(snap)
    _log_hmm(summary, feats)


def _log_hmm(summary: dict, feats) -> None:
    pv = feats.price_vol
    pv_s = (
        f"{pv:.2f}"
        if isinstance(pv, (int, float)) and math.isfinite(float(pv)) and float(pv) > 0
        else "n/a"
    )
    missing = bool(getattr(feats, "price_vol_missing", False))
    posts = summary.get("posteriors")
    poisoned = summary.get("status") == "poisoned"
    if posts is not None:
        try:
            poisoned = poisoned or any(not math.isfinite(float(p)) for p in posts)
        except (TypeError, ValueError):
            poisoned = True
    ent = summary.get("entropy")
    if isinstance(ent, float) and not math.isfinite(ent):
        poisoned = True
    if poisoned:
        log.warning(
            "HMM poisoned — reset  notes=%s price_vol=%s price_vol_missing=%s",
            summary.get("notes"),
            pv_s,
            missing,
        )
        return
    if summary.get("status") == "uninitialized":
        log.info(
            "HMM uninitialized notes=%s price_vol=%s price_vol_missing=%s",
            summary.get("notes"),
            pv_s,
            missing,
        )
        return
    log.info(
        "HMM entropy=%.3f posteriors=%s n_obs=%s price_vol=%s price_vol_missing=%s notes=%s",
        float(ent) if ent is not None else float("nan"),
        summary.get("posteriors"),
        summary.get("n_obs"),
        pv_s,
        missing,
        summary.get("notes"),
    )


def poll_once(
    store: Store,
    settings: Settings,
    retry_delays: tuple[float, ...] = (0, 5, 15, 45),
    snap=None,
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
            if snap is not None:
                try:
                    _hmm_tick(
                        settings,
                        snap,
                        row,
                        store,
                        exclude_id=oid,
                    )
                except Exception:
                    log.exception("HMM tick failed; scrape row was still written")
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
    from pjm_nowcast.model.persistence import load_snapshot, reset_hmm, save_snapshot

    snap_path = Path(settings.snapshot_path)
    snap = load_snapshot(snap_path)
    n_win, restored = _hydrate_price_vol_window(store)
    log.info(
        "Restored LMP vol window from sqlite db=%s n_store=%s window=%s price_vol=%s",
        settings.database_path,
        store.count(),
        n_win,
        f"{restored:.4f}" if restored is not None else "n/a",
    )
    if want_hmm_reset(settings):
        reset_hmm(snap)
        save_snapshot(snap_path, snap)
        log.info(
            "HMM reset applied; unset PJM_NOWCAST_RESET_HMM after a healthy tick "
            "so the next restart does not wipe again"
        )
    log.info(
        "Poller starting interval=%ss jitter=±%ss mock=%s snapshot=%s",
        settings.poll_interval_seconds,
        settings.poll_jitter_seconds,
        settings.mock_mode,
        snap_path,
    )
    while not stop.is_set():
        try:
            await asyncio.to_thread(poll_once, store, settings, (0, 5, 15, 45), snap)
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
