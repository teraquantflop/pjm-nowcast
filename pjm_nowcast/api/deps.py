from __future__ import annotations

from fastapi import Request

from pjm_nowcast.db.store import Store
from pjm_nowcast.settings import Settings


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings
