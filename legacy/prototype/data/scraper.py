"""
Polite scraper for https://www.pjm.com/markets-and-operations

Best-effort static HTML parse for:
  - current load
  - RTO LMP
  - forecasted peak (today) / tomorrow peak
  - selected zonal LMPs

Falls back to previous values with reduced quality on failure.
"""

from __future__ import annotations

import logging
import math
import random
import re
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from config import (
    MOCK_MODE,
    PJM_MARKETS_URL,
    REQUEST_TIMEOUT_SEC,
    USER_AGENT,
    ZONAL_ZONES,
)

log = logging.getLogger("shpnwels.scraper")
ET = ZoneInfo("America/New_York")


def fetch_pjm_markets_page(
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if MOCK_MODE:
        return _mock_fetch(previous)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(
            PJM_MARKETS_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        raw = _parse_html(resp.text)
        if raw is None:
            log.warning("Parse produced no usable numbers")
            return _degraded(previous, reason="parse_empty")
        raw["quality"] = 1.0
        raw["source"] = "pjm_markets_page"
        n_zones = len(raw.get("zonal_lmps") or {})
        log.info(
            "Scrape ok  load=%.0f  rto_lmp=%.2f  peak_today=%s  zones=%d  as_of=%s",
            raw["load_mw"],
            raw["rto_lmp"],
            f"{raw['forecast_peak_today_mw']:.0f}" if raw.get("forecast_peak_today_mw") else "?",
            n_zones,
            raw.get("as_of_text", "?"),
        )
        return raw
    except Exception as e:
        log.warning("Scrape failed: %s", e)
        return _degraded(previous, reason=str(e))


def _parse_html(html: str) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    load = _extract_current_load(text)
    rto = _extract_rto_lmp(text)
    peak_today = _extract_forecast_peak_today(text)
    peak_tom = _extract_forecast_peak_tomorrow(text)
    zonals = _extract_zonal_lmps(text)

    if load is None:
        load = _from_data_attrs(soup, ["currentload", "instantaneousload", "actualload"])
    if rto is None:
        rto = _from_data_attrs(soup, ["rtolmp", "rto_lmp", "lmp"])

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
        "load_mw": float(load) if load is not None else float("nan"),
        "rto_lmp": float(rto) if rto is not None else float("nan"),
        "forecast_peak_today_mw": peak_today,
        "forecast_peak_tomorrow_mw": peak_tom,
        "zonal_lmps": zonals,
        "as_of_text": as_of_text,
        "fetched_at": now_et,
    }


def _extract_current_load(text: str) -> Optional[float]:
    m = re.search(r"([\d,]{4,7})\s*current\s+load\b", text, re.IGNORECASE)
    if m:
        return _to_float(m.group(1))
    m = re.search(
        r"current\s+load\s*(?:\(MW\))?\s*[:\s]*([\d,]{4,7})",
        text,
        re.IGNORECASE,
    )
    if m:
        return _to_float(m.group(1))
    for m in re.finditer(r"current\s+load", text, re.IGNORECASE):
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 60)
        window = text[start:end]
        if re.search(r"forecast", window, re.IGNORECASE):
            continue
        num = _first_number(window)
        if num is not None and 20_000 <= num <= 200_000:
            return num
    return None


def _extract_rto_lmp(text: str) -> Optional[float]:
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


def _extract_forecast_peak_today(text: str) -> Optional[float]:
    """Today's forecasted peak — avoid matching current load or tomorrow."""
    m = re.search(
        r"([\d,]{4,7})\s*forecasted\s+peak\b",
        text,
        re.IGNORECASE,
    )
    if m:
        return _to_float(m.group(1))
    m = re.search(
        r"forecasted\s+peak\s*(?:\(MW\))?\s*[:\s]*([\d,]{4,7})",
        text,
        re.IGNORECASE,
    )
    if m:
        return _to_float(m.group(1))
    return None


def _extract_forecast_peak_tomorrow(text: str) -> Optional[float]:
    # "Tomorrow's Forecast" section usually has a lone peak (MW)
    m = re.search(
        r"Tomorrow'?s?\s+Forecast.*?([\d,]{4,7})\s*peak",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = _to_float(m.group(1))
        if val is not None and 20_000 <= val <= 200_000:
            return val
    m = re.search(
        r"([\d,]{4,7})\s*peak\s*\(MW\).*?Tomorrow|"
        r"Tomorrow.*?([\d,]{4,7})\s*(?:peak)?",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        g = m.group(1) or m.group(2)
        val = _to_float(g) if g else None
        if val is not None and 20_000 <= val <= 200_000:
            return val
    return None


def _extract_zonal_lmps(text: str) -> Dict[str, float]:
    """
    Match lines like 'BGE $35.68' or 'COMED $18.19' for the configured zones.
    """
    out: Dict[str, float] = {}
    for zone in ZONAL_ZONES:
        # ZONE then optional whitespace then $price
        pat = rf"\b{re.escape(zone)}\b\s*\$?\s*([\d]+\.?[\d]*)"
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = _to_float(m.group(1))
            if val is not None and val < 10_000:
                out[zone] = val
    return out


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _first_number(snippet: str) -> Optional[float]:
    m = re.search(r"([\d,]+\.?\d*)", snippet)
    if not m:
        return None
    return _to_float(m.group(1))


def _from_data_attrs(soup: BeautifulSoup, keys: list) -> Optional[float]:
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


def _degraded(
    previous: Optional[Dict[str, Any]],
    reason: str = "",
) -> Dict[str, Any]:
    if previous and "load_mw" in previous and "rto_lmp" in previous:
        out = dict(previous)
        out["quality"] = min(float(previous.get("quality", 1.0)) * 0.5, 0.4)
        out["source"] = f"carried_forward ({reason})"
        out["ts"] = datetime.now(ET)
        log.info("Using carried-forward values (quality=%.2f)", out["quality"])
        return out

    log.warning("No previous data; emitting placeholder quiet values")
    return {
        "ts": datetime.now(ET),
        "load_mw": 85000.0,
        "rto_lmp": 25.0,
        "forecast_peak_today_mw": None,
        "forecast_peak_tomorrow_mw": None,
        "zonal_lmps": {},
        "quality": 0.1,
        "source": f"placeholder ({reason})",
    }


def _mock_fetch(previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    now = datetime.now(ET)
    hour = now.hour + now.minute / 60.0
    base_load = 90000 + 25000 * math.sin((hour - 6) / 24 * 2 * math.pi)
    load = base_load + random.gauss(0, 800)
    base_price = 28 + 18 * max(0, math.sin((hour - 8) / 24 * 2 * math.pi))
    if random.random() < 0.04:
        base_price *= random.uniform(1.8, 3.5)
    price = base_price + random.gauss(0, 1.5)
    peak = max(load + 5000, 120000)
    # synthetic zonals with optional spread
    spread = abs(random.gauss(5, 8)) if price > 50 else abs(random.gauss(2, 2))
    zonals = {}
    for i, z in enumerate(ZONAL_ZONES):
        zonals[z] = max(0.0, price + random.gauss(0, spread / 2) + (i - 2.5))
    return {
        "ts": now,
        "load_mw": float(load),
        "rto_lmp": float(price),
        "forecast_peak_today_mw": float(peak),
        "forecast_peak_tomorrow_mw": float(peak + random.gauss(0, 2000)),
        "zonal_lmps": zonals,
        "quality": 1.0,
        "source": "mock",
        "as_of_text": "mock",
    }
