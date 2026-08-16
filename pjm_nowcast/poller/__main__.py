"""Standalone poller process: python -m pjm_nowcast.poller"""

from __future__ import annotations

import asyncio
import logging
import sys

from pjm_nowcast.db.store import Store
from pjm_nowcast.poller.job import run_poller
from pjm_nowcast.settings import get_settings


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        stream=sys.stdout,
    )
    store = Store(settings.database_path)
    stop = asyncio.Event()

    async def _run() -> None:
        try:
            await run_poller(store, settings, stop)
        finally:
            store.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
