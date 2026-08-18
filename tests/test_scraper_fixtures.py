from pathlib import Path

from pjm_nowcast.ingest.scraper import parse_html

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pjm"
ZONES = ("BGE", "COMED", "DOM", "PEPCO", "PSEG", "JCPL")


def test_parse_sample_html():
    html = (FIXTURES / "sample.html").read_text(encoding="utf-8")
    raw = parse_html(html, ZONES)
    assert raw is not None
    assert raw["load_mw"] == 112400
    assert raw["rto_lmp"] == 32.5
    assert raw["published_peak_today_mw"] == 121000
    assert raw["published_peak_tomorrow_mw"] == 118500
    assert raw["zonal_lmps"]["BGE"] == 34.2
    assert len(raw["zonal_lmps"]) == 6


def test_parse_empty_returns_none():
    html = (FIXTURES / "empty.html").read_text(encoding="utf-8")
    assert parse_html(html, ZONES) is None


def test_parse_flattened_todays_outlook():
    html = (FIXTURES / "todays_outlook_flat.html").read_text(encoding="utf-8")
    raw = parse_html(html, ZONES)
    assert raw is not None
    assert raw["load_mw"] == 122723
    assert raw["published_peak_today_mw"] == 132373
    assert raw["rto_lmp"] == 46.14
    assert raw["load_mw"] != raw["published_peak_today_mw"]


def test_nbsp_and_unpadded_thousands():
    from pjm_nowcast.ingest.scraper import (
        _extract_current_load,
        _extract_forecast_peak_today,
        _normalize_text,
    )

    text = _normalize_text(
        "122723\u00a0current load (MW)\u2009132373 forecasted peak (MW)"
    )
    assert _extract_current_load(text) == 122723
    assert _extract_forecast_peak_today(text) == 132373
    assert _extract_current_load(_normalize_text("1234 current load (MW)")) is None


def test_lmp_only_does_not_fail_scrape():
    html = "<html><body>RTO LMP $46.14 BGE $10</body></html>"
    raw = parse_html(html, ZONES)
    assert raw is not None
    assert raw["rto_lmp"] == 46.14
    assert raw["load_mw"] is None
