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
