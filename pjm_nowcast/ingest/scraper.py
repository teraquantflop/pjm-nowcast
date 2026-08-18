"""Public-page fetch and parse. Poller-only. Do not import from HTTP handlers."""

from __future__ import annotations

import logging
import math
import random
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from pjm_nowcast.settings import Settings

log = logging.getLogger("pjm_nowcast.ingest")
ET = ZoneInfo("America/New_York")


class FetchError(Exception):
    pass


def fetch_page(settings: Settings, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    if settings.mock_mode:
        return mock_fetch(settings)

    headers = {
        "User-Agent": (
            f"pjm-nowcast/1.0 (+{settings.public_base_url}; polite poller; "
            "not a trading bot)"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with httpx.Client(timeout=settings.request_timeout_sec, follow_redirects=True) as client:
            resp = client.get(settings.poll_url, headers=headers)
            resp.raise_for_status()
            raw = parse_html(resp.text, settings.zone_list)
    except Exception as exc:
        log.warning("Fetch failed: %s", exc)
        if settings.poll_carry_forward and previous:
            return _carried(previous, str(exc))
        raise FetchError(str(exc)) from exc

    if raw is None:
        if settings.poll_carry_forward and previous:
            return _carried(previous, "parse_empty")
        raise FetchError("parse produced no usable numbers")

    raw["quality"] = 1.0
    raw["source"] = "public_page"
    log.info(
        "Fetch ok load=%s rto_lmp=%s zones=%d",
        raw.get("load_mw"),
        raw.get("rto_lmp"),
        len(raw.get("zonal_lmps") or {}),
    )
    return raw


def parse_html(html: str, zones: tuple[str, ...]) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    text = _normalize_text(soup.get_text(" ", strip=True))

    load = _extract_current_load(text)
    rto = _extract_rto_lmp(text)
    peak_today = _extract_forecast_peak_today(text)
    peak_tom = _extract_forecast_peak_tomorrow(text)
    zonals = _extract_zonal_lmps(text, zones)

    if load is None:
        load = _from_data_attrs(soup, ["currentload", "instantaneousload", "actualload"])
    if rto is None:
        rto = _from_data_attrs(soup, ["rtolmp", "rto_lmp", "lmp"])

    if load is None:
        log.warning("current load missing; sample=%r", text[:400])

    if load is None and rto is None:
        return None

    as_of_text = None
    m = re.search(
        r"As of\s+(\d{1,2}:\d{2}\s*[ap]\.?m\.?\s*EPT)",
        text,
        re.IGNORECASE,
    )
    if m:
        as_of_text = m.group(1)

    now_et = datetime.now(ET)
    return {
        "ts": now_et,
        "load_mw": float(load) if load is not None else None,
        "rto_lmp": float(rto) if rto is not None else None,
        "published_peak_today_mw": peak_today,
        "published_peak_tomorrow_mw": peak_tom,
        "zonal_lmps": zonals,
        "as_of_text": as_of_text,
        "fetched_at": now_et,
    }


def mock_fetch(settings: Settings) -> dict[str, Any]:
    now = datetime.now(ET)
    hour = now.hour + now.minute / 60.0
    base_load = 90000 + 25000 * math.sin((hour - 6) / 24 * 2 * math.pi)
    load = base_load + random.gauss(0, 800)
    base_price = 28 + 18 * max(0, math.sin((hour - 8) / 24 * 2 * math.pi))
    if random.random() < 0.04:
        base_price *= random.uniform(1.8, 3.5)
    price = base_price + random.gauss(0, 1.5)
    peak = max(load + 5000, 120000)
    spread = abs(random.gauss(5, 8)) if price > 50 else abs(random.gauss(2, 2))
    zonals = {}
    for i, z in enumerate(settings.zone_list):
        zonals[z] = max(0.0, price + random.gauss(0, spread / 2) + (i - 2.5))
    return {
        "ts": now,
        "load_mw": float(load),
        "rto_lmp": float(price),
        "published_peak_today_mw": float(peak),
        "published_peak_tomorrow_mw": float(peak + random.gauss(0, 2000)),
        "zonal_lmps": zonals,
        "quality": 1.0,
        "source": "mock",
        "as_of_text": "mock",
        "fetched_at": now,
    }


def _carried(previous: dict[str, Any], reason: str) -> dict[str, Any]:
    out = dict(previous)
    out["quality"] = min(float(previous.get("quality", 1.0)) * 0.5, 0.4)
    out["source"] = f"carried_forward ({reason})"
    out["ts"] = datetime.now(ET)
    out["fetched_at"] = datetime.now(ET)
    return out


# 1,234 or 123456, optional decimals. Not the old [\d,]{4,7} (too tight).
_MW_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MW_UNIT = r"(?:\(\s*MW\s*\)|MW)"
_RTO_MW_MIN = 20_000.0
_RTO_MW_MAX = 250_000.0

_LOAD_LABEL = r"current\s+load(?:\s*\(\s*MW\s*\))?"
_PEAK_TODAY_LABEL = r"forecasted\s+peak(?:\s*\(\s*MW\s*\))?"


def _normalize_text(text: str) -> str:
    for src in ("\u00a0", "\u202f", "\u2007", "\u2009", "\u200a", "\u2060", "\ufeff"):
        text = text.replace(src, " ")
    return re.sub(r"[ \t\r\n\f]+", " ", text).strip()


def _sane_rto_mw(val: float | None) -> float | None:
    if val is None or not math.isfinite(val):
        return None
    if _RTO_MW_MIN <= val <= _RTO_MW_MAX:
        return val
    return None


def _labeled_mw(text: str, label: str) -> float | None:
    """Number immediately before or after a label; optional MW between them."""
    before = re.search(
        rf"(?P<num>{_MW_NUM})\s*(?:{_MW_UNIT})?\s*{label}",
        text,
        re.IGNORECASE,
    )
    if before:
        return _sane_rto_mw(_to_float(before.group("num")))

    after = re.search(
        rf"{label}\s*(?:{_MW_UNIT})?\s*[:\s]*(?P<num>{_MW_NUM})",
        text,
        re.IGNORECASE,
    )
    if after:
        # Do not steal the next metric's leading number
        # (e.g. load after-label grabbing forecasted-peak MW).
        rest = text[after.end() :]
        if re.match(rf"\s*(?:{_MW_UNIT})?\s*forecasted\s+peak", rest, re.IGNORECASE):
            return None
        return _sane_rto_mw(_to_float(after.group("num")))
    return None


def _extract_current_load(text: str) -> float | None:
    return _labeled_mw(text, _LOAD_LABEL)


def _extract_rto_lmp(text: str) -> float | None:
    m = re.search(
        r"RTO\s+LMP\s*(?:\(\$\))?\s*[:\s]*\$?\s*([\d]+\.?[\d]*)",
        text,
        re.IGNORECASE,
    )
    if m:
        return _to_float(m.group(1))
    m = re.search(r"\$?\s*([\d]+\.?[\d]*)\s*RTO\s+LMP", text, re.IGNORECASE)
    if m:
        return _to_float(m.group(1))
    m = re.search(r"RTO[^\$]{0,30}\$?\s*([\d]+\.?[\d]*)", text, re.IGNORECASE)
    if m:
        val = _to_float(m.group(1))
        if val is not None and val < 10_000:
            return val
    return None


def _extract_forecast_peak_today(text: str) -> float | None:
    return _labeled_mw(text, _PEAK_TODAY_LABEL)


def _extract_forecast_peak_tomorrow(text: str) -> float | None:
    m = re.search(
        rf"Tomorrow'?s?\s+Forecast.*?({_MW_NUM})\s*peak",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = _sane_rto_mw(_to_float(m.group(1)))
        if val is not None:
            return val
    m = re.search(
        rf"({_MW_NUM})\s*peak\s*\(MW\).*?Tomorrow|"
        rf"Tomorrow.*?({_MW_NUM})\s*(?:peak)?",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        g = m.group(1) or m.group(2)
        return _sane_rto_mw(_to_float(g) if g else None)
    return None


def _extract_zonal_lmps(text: str, zones: tuple[str, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    for zone in zones:
        pat = rf"\b{re.escape(zone)}\b\s*\$?\s*([\d]+\.?[\d]*)"
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = _to_float(m.group(1))
            if val is not None and val < 10_000:
                out[zone] = val
    return out


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _first_number(snippet: str) -> float | None:
    m = re.search(r"([\d,]+\.?\d*)", snippet)
    if not m:
        return None
    return _to_float(m.group(1))


def _from_data_attrs(soup: BeautifulSoup, keys: list[str]) -> float | None:
    for tag in soup.find_all(True):
        for attr, val in tag.attrs.items():
            if not isinstance(val, str):
                continue
            low = (attr + str(val)).lower()
            if any(k in low for k in keys):
                num = _first_number(val)
                if num is not None:
                    return num
    return None
