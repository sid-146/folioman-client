"""Unit tests for individual price feed adapters."""

from datetime import date
from decimal import Decimal
import io
import zipfile
import pytest
import respx
import httpx

from folioman_client.core.price_feeds import (
    amfi_bulk,
    captnemo,
    coingecko,
    mfapi,
    nse_bhavcopy,
    nse_history,
    yfinance_feed,
)
from folioman_client.core.price_feeds.errors import NAVFetchError, PriceFetchError


def test_mfapi_fetch_latest():
    with respx.mock(base_url="https://api.mfapi.in") as rmock:
        rmock.get("/mf/122639/latest").respond(
            200,
            json={
                "meta": {"scheme_code": 122639, "scheme_name": "Parag Parikh Flexi Cap Fund"},
                "data": [{"date": "10-04-2026", "nav": "75.4123"}],
                "status": "SUCCESS",
            },
        )
        point = mfapi.fetch_latest_nav("122639")
        assert point is not None
        assert point.date == date(2026, 4, 10)
        assert point.nav == Decimal("75.4123")


def test_mfapi_fetch_history_and_filters():
    with respx.mock(base_url="https://api.mfapi.in") as rmock:
        rmock.get("/mf/122639").respond(
            200,
            json={
                "meta": {
                    "scheme_code": 122639,
                    "isin_growth": "INF879O01019",
                },
                "data": [
                    {"date": "10-04-2026", "nav": "75.4123"},
                    {"date": "09-04-2026", "nav": "74.8910"},
                    {"date": "08-04-2026", "nav": "74.5000"},
                ],
                "status": "SUCCESS",
            },
        )
        # Oldest first
        history = mfapi.fetch_nav_history("122639", since=date(2026, 4, 9))
        assert history.amfi_code == "122639"
        assert history.isin == "INF879O01019"
        assert len(history.points) == 2
        assert history.points[0].date == date(2026, 4, 9)
        assert history.points[1].date == date(2026, 4, 10)


def test_captnemo_fetch_latest_and_history():
    with respx.mock(base_url="https://mf.captnemo.in") as rmock:
        rmock.get("/nav/INF879O01019").respond(
            200,
            json={
                "ISIN": "INF879O01019",
                "name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "nav": 75.4123,
                "date": "2026-04-10",
                "historical_nav": [
                    ["2026-04-08", 74.5000],
                    ["2026-04-09", 74.8910],
                    ["2026-04-10", 75.4123],
                ],
            },
        )
        latest = captnemo.fetch_latest_nav("INF879O01019")
        assert latest is not None
        assert latest.date == date(2026, 4, 10)
        assert latest.nav == Decimal("75.4123")

        history = captnemo.fetch_nav_history("INF879O01019", since=date(2026, 4, 9))
        assert len(history.points) == 2
        assert history.points[0].date == date(2026, 4, 9)


def test_amfi_bulk_parse():
    sample_text = (
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "Open Ended Schemes ( Equity Scheme - Flexi Cap Fund )\n"
        "Parag Parikh Mutual Fund\n"
        "122639;INF879O01019;INF879O01027;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;75.4123;10-Apr-2026\n"
        "122640;INF879O01035;-;Parag Parikh Flexi Cap Fund - Regular - Growth;N.A.;10-Apr-2026\n"
    )
    result = amfi_bulk.parse_navall(sample_text)
    assert "122639" in result
    assert "INF879O01019" in result
    assert "INF879O01027" in result
    assert result["122639"].nav == Decimal("75.4123")
    assert result["122639"].date == date(2026, 4, 10)
    # N.A. row skipped
    assert "122640" not in result


def test_yfinance_fetch_quote():
    with respx.mock(base_url="https://query1.finance.yahoo.com") as rmock:
        rmock.get("/v8/finance/chart/TCS.NS").respond(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": 3850.50,
                                "currency": "INR",
                            }
                        }
                    ],
                    "error": None,
                }
            },
        )
        quote = yfinance_feed.fetch_quote("TCS", exchange="NSE")
        assert quote is not None
        assert quote.price == Decimal("3850.5")
        assert quote.source == "yfinance"


def test_nse_history_parse_csv():
    csv_data = (
        '"Symbol","Series","Date","Prev Close","Open Price","High Price","Low Price","Last Price","Close Price"\n'
        '"TCS","EQ","08-Apr-2026","3,800.00","3,810.00","3,860.00","3,790.00","3,852.00","3,850.50"\n'
        '"TCS","EQ","09-Apr-2026","3,850.50","3,855.00","3,890.00","3,840.00","3,875.00","3,870.00"\n'
    )
    points = nse_history._parse_csv(csv_data)
    assert len(points) == 2
    assert points[0].date == date(2026, 4, 8)
    assert points[0].nav == Decimal("3850.50")
    assert points[1].date == date(2026, 4, 9)
    assert points[1].nav == Decimal("3870.00")


def test_nse_bhavcopy_parse_udiff():
    csv_content = (
        "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,ClsPric\n"
        "2026-04-10,2026-04-10,CM,NSE,STK,1234,INE467B01029,TCS,EQ,3870.00\n"
        "2026-04-10,2026-04-10,CM,NSE,STK,5678,INE002A01018,RELIANCE,EQ,2950.25\n"
    )
    res = nse_bhavcopy.parse_bhavcopy_csv(csv_content, date(2026, 4, 10))
    assert "TCS" in res
    assert "RELIANCE" in res
    assert res["TCS"].nav == Decimal("3870.00")
    assert res["RELIANCE"].nav == Decimal("2950.25")


def test_coingecko_fetch_quotes():
    with respx.mock(base_url="https://api.coingecko.com") as rmock:
        rmock.get("/api/v3/simple/price").respond(
            200,
            json={
                "bitcoin": {"inr": 8500000.0},
                "ethereum": {"inr": 250000.0},
            },
        )
        quotes = coingecko.fetch_quotes(["bitcoin", "ethereum"])
        assert "bitcoin" in quotes
        assert "ethereum" in quotes
        assert quotes["bitcoin"].price == Decimal("8500000.0")
        assert quotes["ethereum"].currency == "INR"
