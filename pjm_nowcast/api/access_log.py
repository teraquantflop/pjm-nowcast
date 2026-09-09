"""One JSON access line per request. Join Railway Flow on requestId."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from pjm_nowcast.payments.routes import match_paid_path

log = logging.getLogger("pjm_nowcast.access")


def _header_map(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in scope.get("headers") or []:
        out[k.decode("latin1").lower()] = v.decode("latin1")
    return out


def _request_id(headers: dict[str, str]) -> str:
    for key in ("x-request-id", "x-railway-request-id"):
        val = (headers.get(key) or "").strip()
        if val:
            return val
    return str(uuid.uuid4())


def _payment(path: str, status: int) -> str:
    paid = match_paid_path(path) is not None
    if status == 402:
        return "challenge"
    if 200 <= status < 300:
        return "settled" if paid else "free"
    return "other"


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = _header_map(scope)
        rid = _request_id(headers)
        method = str(scope.get("method") or "")
        path = str(scope.get("path") or "")
        ua = headers.get("user-agent") or None
        started = time.perf_counter()
        status_box: dict[str, int] = {}

        async def inner(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_box["status"] = int(message.get("status") or 0)
                hdrs = list(message.get("headers") or [])
                keys = {k.lower() for k, _ in hdrs}
                if b"x-request-id" not in keys:
                    hdrs.append((b"x-request-id", rid.encode("ascii", errors="replace")))
                message = {**message, "headers": hdrs}
            await send(message)

        await self.app(scope, receive, inner)
        status = int(status_box.get("status") or 0)
        ms = int((time.perf_counter() - started) * 1000)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "requestId": rid,
            "method": method,
            "path": path,
            "status": status,
            "ms": ms,
            "payment": _payment(path, status),
            "network": None,
            "uaApp": ua,
        }
        log.info("%s", json.dumps(line, separators=(",", ":")))
