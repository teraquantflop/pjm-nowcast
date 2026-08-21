"""Optional OptionBookClient header check for paid routes."""

from __future__ import annotations

import hmac
import logging

HEADER = "optionbookclient"

log = logging.getLogger("pjm_nowcast.payments")


def header_matches(expected: str | None, got: str | None) -> bool:
    if not expected or not got:
        return False
    a = expected.encode("utf-8")
    b = got.encode("utf-8")
    if len(a) != len(b):
        return False
    ok = hmac.compare_digest(a, b)
    if ok:
        log.info("optionbook_client=%s", True)
    return ok
