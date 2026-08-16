from __future__ import annotations

from pjm_nowcast.settings import Settings


def client_ip(headers: dict[str, str], settings: Settings, fallback: str = "127.0.0.1") -> str:
    if not settings.trust_proxy:
        return fallback
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if not xff:
        return fallback
    # leftmost is original client when the edge appends
    return xff.split(",")[0].strip() or fallback
