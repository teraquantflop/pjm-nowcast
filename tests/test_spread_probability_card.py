from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from pjm_nowcast.api.app import create_app
from pjm_nowcast.db.store import Store, target_hour_ept
from pjm_nowcast.settings import Settings
from pjm_nowcast.spread_card import (
    SPREAD_CARD_BAR,
    SPREAD_CARD_MCP_TOOL,
    SPREAD_CARD_PATH,
    SPREAD_CARD_PRODUCT,
    SPREAD_CARD_RELATED,
    SPREAD_CARD_TITLE,
    SPREAD_CARD_WHEN_NOT_TO_USE,
    SPREAD_CARD_WHEN_TO_USE,
)
from pjm_nowcast.stats.probability_card import is_nerc_holiday, is_on_peak_hour

ET = ZoneInfo("America/New_York")
ASOF = datetime(2026, 6, 12, 16, 30, tzinfo=ET)
RTO = 40.0
ZONES = ("BGE", "COMED", "DOM", "PEPCO", "PSEG", "JCPL")


def _zonals(spread: float, rto: float = RTO) -> dict[str, float]:
    # All zones equal so p95-p05 is 0. Underlier is zone - rto.
    return {z: rto + float(spread) for z in ZONES}


def _obs(
    store: Store,
    ts: datetime,
    spr_act: float,
    *,
    rto: float = RTO,
) -> None:
    store.insert_observation(
        ts=ts,
        fetched_at=ts,
        load_mw=100000.0,
        rto_lmp=rto,
        published_peak_today_mw=None,
        published_peak_tomorrow_mw=None,
        quality=1.0,
        source="test",
        as_of_text=None,
        load_ramp_mw=None,
        zonals=_zonals(spr_act, rto),
    )


def _snap(store: Store, hour: datetime, spr_nc: float) -> None:
    store.insert_nowcast_snapshot(
        {
            "fetched_at_utc": hour.astimezone(ET).isoformat(),
            "asof": hour.isoformat(),
            "target_hour_ept": target_hour_ept(hour),
            "rto_nc": RTO,
            "zone_nc": None,
            "spr_nc": spr_nc,
            "load_nc": 100000.0,
            "price_vol": None,
            "price_vol_missing": True,
            "mix_std_price": None,
            "mix_n_obs": None,
        }
    )


def _seed_hour(store: Store, local: datetime, spr_act: float, spr_nc: float) -> None:
    _obs(store, local, spr_act)
    _snap(store, local, spr_nc)


def seed_card_fixture(store: Store) -> None:
    # Mon 8 – Fri 12 June 2026. Quiet hours 10 and 14 at 10. Max hour 17.
    max_by_day = {
        datetime(2026, 6, 8).date(): 20.0,
        datetime(2026, 6, 9).date(): 20.0,
        datetime(2026, 6, 10).date(): 10.0,
        datetime(2026, 6, 11).date(): 10.0,
        datetime(2026, 6, 12).date(): 20.0,
    }
    for day, peak in max_by_day.items():
        for hour, spr in ((10, 10.0), (14, 10.0), (17, peak)):
            local = datetime(day.year, day.month, day.day, hour, 0, tzinfo=ET)
            spr_nc = 7.0 if (day.isoformat() == "2026-06-11" and hour == 17) else 9.0
            _seed_hour(store, local, spr, spr_nc)
    # Open hour Friday 16:00 — in the latest nowcast, dropped from the sample.
    open_hour = datetime(2026, 6, 12, 16, 0, tzinfo=ET)
    _seed_hour(store, open_hour, 11.0, 30.0)
    # Unpaired: observation without snapshot, snapshot without observation.
    wed = datetime(2026, 6, 10, 12, 0, tzinfo=ET)
    _obs(store, wed, 99.0)
    orphan = datetime(2026, 6, 10, 11, 0, tzinfo=ET)
    _snap(store, orphan, 99.0)
    # Weekend hour must not pool.
    sat = datetime(2026, 6, 6, 14, 0, tzinfo=ET)
    _seed_hour(store, sat, 80.0, 80.0)


def test_on_peak_and_nerc():
    weekday = datetime(2026, 6, 8, 10, 0, tzinfo=ET)
    assert is_on_peak_hour(weekday)
    saturday = datetime(2026, 6, 6, 10, 0, tzinfo=ET)
    assert not is_on_peak_hour(saturday)
    # Independence Day 2026 is Saturday 4 Jul; observed Friday 3 Jul.
    assert is_nerc_holiday(datetime(2026, 7, 3).date())
    assert not is_on_peak_hour(datetime(2026, 7, 3, 14, 0, tzinfo=ET))


def test_card_rules(client, store):
    seed_card_fixture(store)
    r = client.post(
        SPREAD_CARD_PATH,
        json={"lookbackDays": 5, "asOf": ASOF.isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sample"]["tag"] == "high-congestion-season"
    assert body["sample"]["dayCount"] == 5
    assert body["sample"]["firstEptDate"] == "2026-06-08"
    assert body["sample"]["lastEptDate"] == "2026-06-12"
    assert body["K"] == pytest.approx(10.0)
    assert body["hitDays"] == 2
    assert body["hitRate"] == pytest.approx(0.4)
    assert body["avgPayoff"] == pytest.approx(4.0)
    assert body["dailyMaxP50"] == pytest.approx(10.0)
    assert body["dailyMaxP95"] == pytest.approx(20.0)
    latest = body["latestCompleteDay"]
    assert latest["eptDate"] == "2026-06-11"
    assert latest["spr_act"] == pytest.approx(10.0)
    assert latest["spr_nc"] == pytest.approx(7.0)
    assert latest["miss"] == pytest.approx(3.0)
    assert "2026-06-12T16:00" not in (latest.get("maxHourEpt") or "")
    nc = body["latestNowcast"]
    assert nc["spr_nc"] == pytest.approx(30.0)
    assert nc["K"] == pytest.approx(10.0)
    assert nc["throughStrike"] is True
    dumped = str(body).lower()
    assert "forecast" not in body
    assert "sigma_atm" not in body
    assert "sigmaatm" not in dumped
    assert body.get("mid") is None
    assert "black" not in body
    assert "buyerBeware" in body
    assert "not a forecast" in body["buyerBeware"]


def test_settled_print_not_closest_asof(client, store):
    """Old closest-asof join would report hitDays == 3 on this fixture."""
    prints = (188.0, 447.0, 428.0, 746.0, 58.0)
    nowcasts = (58.0, 145.0, 788.0, 931.0, 63.0)
    days = (
        datetime(2026, 10, 5).date(),
        datetime(2026, 10, 6).date(),
        datetime(2026, 10, 7).date(),
        datetime(2026, 10, 8).date(),
        datetime(2026, 10, 9).date(),
    )
    for i, day in enumerate(days):
        quiet = 50.0 if i == 4 else 76.0
        for hour, spr in ((10, 50.0), (14, quiet)):
            local = datetime(day.year, day.month, day.day, hour, 0, tzinfo=ET)
            _seed_hour(store, local, spr, spr)
        hb18 = datetime(day.year, day.month, day.day, 18, 0, tzinfo=ET)
        # Snapshot asof = hour start. Closest-asof would pick the nowcast print.
        _snap(store, hb18, nowcasts[i])
        _obs(store, hb18, nowcasts[i])
        settled = hb18.replace(minute=45)
        _obs(store, settled, prints[i])
    asof = datetime(2026, 10, 9, 23, 0, tzinfo=ET)
    r = client.post(
        SPREAD_CARD_PATH,
        json={"lookbackDays": 5, "asOf": asof.isoformat()},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["K"] == pytest.approx(76.0, abs=1.0)
    assert body["hitDays"] == 4
    latest = body["latestCompleteDay"]
    assert latest["eptDate"] == "2026-10-09"
    assert latest["spr_act"] == pytest.approx(58.0)
    assert latest["spr_nc"] == pytest.approx(63.0)
    assert latest["miss"] == pytest.approx(58.0 - 63.0)
    assert latest["miss"] != pytest.approx(0.0)


def test_open_hour_dropped_from_sample(client, store):
    seed_card_fixture(store)
    body = client.post(
        SPREAD_CARD_PATH,
        json={"lookbackDays": 5, "asOf": ASOF.isoformat()},
    ).json()
    # Friday 16:00 spr_act=11 would change daily max if included.
    assert body["sample"]["lastEptDate"] == "2026-06-12"
    assert body["hitDays"] == 2


def test_lookback_bounds_and_insufficient(client, store):
    r = client.post(SPREAD_CARD_PATH, json={"lookbackDays": 31})
    assert r.status_code == 400
    seed_card_fixture(store)
    # Two days only: asOf Tuesday with lookback 2.
    asof = datetime(2026, 6, 9, 18, 0, tzinfo=ET)
    r = client.post(
        SPREAD_CARD_PATH,
        json={"lookbackDays": 2, "asOf": asof.isoformat()},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "insufficient_sample"


def test_empty_store_503(client):
    r = client.post(SPREAD_CARD_PATH, json={"lookbackDays": 5})
    assert r.status_code == 503


def test_catalog_surfaces(client):
    card = client.get("/").json()
    paths = {e["path"] for e in card["endpoints"]}
    assert SPREAD_CARD_PATH in paths
    assert f"POST {SPREAD_CARD_PATH}" in card["prices"]
    assert card["prices"][f"POST {SPREAD_CARD_PATH}"] == "$0.25"
    ep = next(e for e in card["endpoints"] if e["path"] == SPREAD_CARD_PATH)
    blob = str(ep) + str(card.get("relatedResources"))
    assert SPREAD_CARD_TITLE in blob
    assert SPREAD_CARD_PRODUCT in blob
    assert SPREAD_CARD_BAR in blob
    assert SPREAD_CARD_WHEN_TO_USE in blob
    assert SPREAD_CARD_WHEN_NOT_TO_USE in blob
    assert SPREAD_CARD_RELATED in blob

    spec = client.get("/openapi.json").json()
    post = spec["paths"][SPREAD_CARD_PATH]["post"]
    assert post["x-payment-info"]["price"] == "$0.25"
    assert "402" in post["responses"]
    assert SPREAD_CARD_TITLE in (post["summary"] + post["description"])

    resources = client.get("/.well-known/x402-resources").json()["resources"]
    paths = {r["path"] for r in resources}
    assert SPREAD_CARD_PATH in paths
    item = next(r for r in resources if r["path"] == SPREAD_CARD_PATH)
    assert item["price"] == "$0.25"
    assert SPREAD_CARD_TITLE in item["description"]

    mcp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    ).json()
    tools = {t["name"]: t for t in mcp["result"]["tools"]}
    assert SPREAD_CARD_MCP_TOOL in tools
    tool = tools[SPREAD_CARD_MCP_TOOL]
    assert tool["_meta"]["x402"]["price"] == "$0.25"
    assert tool["_meta"]["x402"]["httpPath"] == SPREAD_CARD_PATH
    assert SPREAD_CARD_WHEN_TO_USE in tool["whenToUse"]
    assert SPREAD_CARD_WHEN_NOT_TO_USE in tool["whenNotToUse"]
    assert SPREAD_CARD_WHEN_TO_USE in tool["description"]


def test_unpaid_is_402(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "p.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.post(SPREAD_CARD_PATH, json={})
        assert r.status_code == 402
        assert r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
        assert "payTo" not in r.text
        import base64
        import json

        raw = r.headers.get("payment-required") or r.headers.get("PAYMENT-REQUIRED")
        challenge = json.loads(base64.b64decode(raw).decode("utf-8"))
        assert challenge["accepts"][0]["amount"] == "250000"
        assert "bazaar" in (challenge.get("extensions") or {})
        assert "payTo" not in r.text


def test_optionbook_header_clears_card(tmp_path, monkeypatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("RUN_POLLER", "false")
    monkeypatch.setenv("X402_DISABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_RPS", "1000")
    monkeypatch.setenv("RATE_LIMIT_BURST", "1000")
    ob_id = "ob-test-id-aaaa"
    settings = Settings(
        env="test",
        run_poller=False,
        x402_disabled=False,
        data_dir=tmp_path,
        database_path=tmp_path / "ob.sqlite",
        public_base_url="http://testserver",
        pay_to_evm_address="0x1111111111111111111111111111111111111111",
        rate_limit_rps=1000,
        rate_limit_burst=1000,
        optionbook_id=ob_id,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        seed_card_fixture(c.app.state.store)
        miss = c.post(SPREAD_CARD_PATH, json={"lookbackDays": 5, "asOf": ASOF.isoformat()})
        assert miss.status_code == 402
        hit = c.post(
            SPREAD_CARD_PATH,
            json={"lookbackDays": 5, "asOf": ASOF.isoformat()},
            headers={"OptionBookClient": ob_id},
        )
        assert hit.status_code == 200, hit.text
        assert hit.json()["sample"]["tag"] == "high-congestion-season"
