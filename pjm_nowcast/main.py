"""uvicorn pjm_nowcast.main:app"""

from __future__ import annotations

import logging
import sys

from pjm_nowcast.api.app import create_app
from pjm_nowcast.settings import get_settings

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    stream=sys.stdout,
)

app = create_app(settings)
