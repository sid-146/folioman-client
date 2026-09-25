"""Comprehensive unit tests for FoliomanClient and API resources."""

from __future__ import annotations

import time
from decimal import Decimal

import httpx
import pytest
import respx

from folioman_client.client import FoliomanClient
from folioman_client.errors import (
    FoliomanAPIError,
    FoliomanAuthError,
    FoliomanNotFoundError,
)
from folioman_client.models import (
    CapitalGainsReport,
    Investor,
    InvestorDetail,
    PortfolioSummary,
    SchemeDetail,
    Transaction,
    ValuationStatus,
    ValueSeries,
)
from .conftest import create_mock_jwt

BASE_URL = "http://folioman.local:8000"


@pytest.fixture
def mock_tokens() -> tuple[str, str]:
    access = create_mock_jwt(time.time() + 3600)
    refresh = create_mock_jwt(time.time() + 86400)
    return access, refresh


@pytest.mark.asyncio
async def test_authenticated_api_request_adds_bearer_token(
    mock_tokens: tuple[str, str],
) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.post("/api/auth/token/pair").respond(
                200,
                json={"access": access, "refresh": refresh},
            )
            api_route = respx_mock.get("/api/investors/").respond(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "Sudhanwa",
                        "email": "sudhanwa@example.com",
                        "is_huf": False,
                        "relation": "",
                        "family_id": None,
                        "has_pan": True,
                        "pan_locked": True,
                    }
                ],
            )

            investors = await client.investors.list()

            assert len(investors) == 1
            assert isinstance(investors[0], Investor)
            assert investors[0].id == 1
            assert investors[0].name == "Sudhanwa"
            assert api_route.called
            assert (
                api_route.calls.last.request.headers["Authorization"]
                == f"Bearer {access}"
            )


@pytest.mark.asyncio
async def test_401_triggers_refresh_and_retry(mock_tokens: tuple[str, str]) -> None:
    initial_access, refresh = mock_tokens
    fresh_access = create_mock_jwt(time.time() + 7200)

    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        # Pre-seed existing tokens
        client._auth._access_token = initial_access
        client._auth._refresh_token = refresh

        with respx.mock(base_url=BASE_URL) as respx_mock:
            # 1. API route first returns 401, then returns 200 on retry
            investor_route = respx_mock.get("/api/investors/1")
            investor_route.side_effect = [
                httpx.Response(
                    401, json={"detail": "Given token not valid for any token type"}
                ),
                httpx.Response(
                    200,
                    json={
                        "id": 1,
                        "name": "Sudhanwa",
                        "email": "test@example.com",
                        "is_huf": False,
                        "relation": "",
                        "family_id": None,
                        "has_pan": True,
                        "pan_locked": True,
                        "pan_masked": "XXXXXX1234",
                    },
                ),
            ]

            # 2. Refresh endpoint returns new access token
            refresh_route = respx_mock.post("/api/auth/token/refresh").respond(
                200,
                json={"access": fresh_access},
            )

            investor = await client.investors.get(1)

            assert isinstance(investor, InvestorDetail)
            assert investor.id == 1
            assert investor.pan_masked == "XXXXXX1234"
            assert refresh_route.called
            assert investor_route.call_count == 2
            # Second call used the fresh access token
            assert (
                investor_route.calls.last.request.headers["Authorization"]
                == f"Bearer {fresh_access}"
            )


@pytest.mark.asyncio
async def test_404_raises_folioman_not_found_error(
    mock_tokens: tuple[str, str],
) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/999").respond(
                404, json={"detail": "Not found"}
            )

            with pytest.raises(
                FoliomanNotFoundError, match="Resource not found at /api/investors/999"
            ):
                await client.investors.get(999)


@pytest.mark.asyncio
async def test_500_raises_folioman_api_error(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/transactions").respond(
                500,
                json={"detail": "Database error"},
            )

            with pytest.raises(FoliomanAPIError) as exc_info:
                await client.transactions.list(1)

            assert exc_info.value.status_code == 500
            assert "Database error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_portfolio_and_holdings_retrieval(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        summary_payload = {
            "investor_id": 1,
            "as_of": "2026-09-13",
            "total_inr": "500000.00",
            "is_provisional": False,
            "holdings_count": 2,
            "integrity_unit_count": 2,
            "tax_ready_count": 2,
            "needs_attention_count": 0,
            "snapshot_count": 0,
            "stale_count": 0,
            "unpriced_fund_count": 0,
            "last_import_at": "2026-09-13T10:00:00Z",
            "day_change_inr": "1500.50",
            "xirr": 0.154,
            "period_returns": [
                {"period": "1Y", "annualized": 0.145, "absolute": 0.145, "days": 365}
            ],
            "asset_mix": [{"security_type": "mf", "value_inr": "500000.00"}],
            "amc_mix": [{"label": "HDFC Mutual Fund", "value_inr": "500000.00"}],
            "category_mix": [{"label": "Equity", "value_inr": "500000.00"}],
            "top_holdings": [],
            "holdings": [
                {
                    "security_id": 10,
                    "name": "HDFC Top 100 Fund",
                    "security_type": "mf",
                    "symbol": "",
                    "amc": "HDFC Mutual Fund",
                    "category": "Equity",
                    "units": "500.000",
                    "value_inr": "300000.00",
                    "invested_inr": "200000.00",
                    "latest_nav": "600.00",
                    "return_pct": 0.5,
                    "xirr": 0.16,
                    "day_change_inr": "1000.00",
                    "day_change_pct": 0.0033,
                },
                {
                    "security_id": 11,
                    "name": "Parag Parikh Flexi Cap Fund",
                    "security_type": "mf",
                    "symbol": "",
                    "amc": "PPFAS",
                    "category": "Equity",
                    "units": "2000.000",
                    "value_inr": "200000.00",
                    "invested_inr": "150000.00",
                    "latest_nav": "100.00",
                    "return_pct": 0.33,
                    "xirr": 0.14,
                    "day_change_inr": "500.50",
                    "day_change_pct": 0.0025,
                },
            ],
        }

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/summary").respond(
                200, json=summary_payload
            )

            # Test portfolio.get
            portfolio = await client.portfolio.get(1)
            assert isinstance(portfolio, PortfolioSummary)
            assert portfolio.investor_id == 1
            assert portfolio.total_inr == Decimal("500000.00")
            assert len(portfolio.holdings) == 2

            # Test holdings.list (convenience method using portfolio.get)
            holdings = await client.holdings.list(1)
            assert len(holdings) == 2
            assert holdings[0].security_id == 10
            assert holdings[0].name == "HDFC Top 100 Fund"
            assert holdings[0].units == Decimal("500.000")
            assert holdings[1].security_id == 11


@pytest.mark.asyncio
async def test_holdings_get_scheme_detail(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        scheme_payload = {
            "security": {
                "id": 10,
                "name": "HDFC Top 100 Fund",
                "isin": "INF179K01BE2",
                "symbol": "",
                "security_type": "mf",
                "amfi_code": "118989",
                "amc": "HDFC Mutual Fund",
                "category": "Equity",
            },
            "as_of": "2026-09-13",
            "units": "500.000",
            "value_inr": "300000.00",
            "invested_inr": "200000.00",
            "return_pct": 0.5,
            "xirr": 0.16,
            "xirr_status": "valid",
            "day_change_inr": "1000.00",
            "day_change_pct": 0.0033,
            "latest_nav": "600.00",
            "latest_nav_date": "2026-09-12",
            "has_transactions": True,
            "partial_history": False,
            "folios": [],
            "nav_history": [{"date": "2026-09-12", "nav": "600.00"}],
            "transactions": [],
        }

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/holdings/10").respond(
                200, json=scheme_payload
            )

            scheme = await client.holdings.get(1, 10)
            assert isinstance(scheme, SchemeDetail)
            assert scheme.security.isin == "INF179K01BE2"
            assert scheme.units == Decimal("500.000")
            assert len(scheme.nav_history) == 1
            assert scheme.nav_history[0].nav == Decimal("600.00")


@pytest.mark.asyncio
async def test_transactions_list(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        txns_payload = [
            {
                "id": 101,
                "investor_id": 1,
                "security_id": 10,
                "folio_id": 1,
                "date": "2024-01-15",
                "transaction_type": "purchase",
                "units": "100.000",
                "nav_or_price": "500.00",
                "amount": "50000.00",
                "fees": "0",
                "stamp_duty": "2.5",
                "brokerage": "0",
                "currency": "INR",
                "source": "cams_cas",
                "narration": "Systematic Investment",
                "cost_basis_complete": True,
                "balance": "100.000",
            }
        ]

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/transactions").respond(
                200, json=txns_payload
            )

            txns = await client.transactions.list(1)
            assert len(txns) == 1
            assert isinstance(txns[0], Transaction)
            assert txns[0].id == 101
            assert txns[0].units == Decimal("100.000")
            assert txns[0].transaction_type == "purchase"


@pytest.mark.asyncio
async def test_valuations_series_and_status(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        series_payload = {
            "investor_id": 1,
            "start": "2024-01-01",
            "end": "2024-03-01",
            "granularity": "monthly",
            "points": [
                {
                    "date": "2024-01-31",
                    "value_inr": "100000.00",
                    "invested_inr": "95000.00",
                    "stale": False,
                },
                {
                    "date": "2024-02-29",
                    "value_inr": "105000.00",
                    "invested_inr": "95000.00",
                    "stale": False,
                },
            ],
        }
        status_payload = {
            "investor_id": 1,
            "status": "ready",
            "computed_through": "2024-03-01",
            "is_provisional": False,
        }

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/value-series").respond(
                200, json=series_payload
            )
            respx_mock.get("/api/investors/1/valuation-status").respond(
                200, json=status_payload
            )

            series = await client.valuations.list(1, granularity="monthly")
            assert isinstance(series, ValueSeries)
            assert len(series.points) == 2
            assert series.points[1].value_inr == Decimal("105000.00")

            status = await client.valuations.status(1)
            assert isinstance(status, ValuationStatus)
            assert status.status == "ready"


@pytest.mark.asyncio
async def test_capital_gains_list_and_get(mock_tokens: tuple[str, str]) -> None:
    access, refresh = mock_tokens
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = access
        client._auth._refresh_token = refresh

        by_fy_payload = [
            {"fy": "2023-24", "stcg": "12000.00", "ltcg": "45000.00"},
            {"fy": "2024-25", "stcg": "5000.00", "ltcg": "80000.00"},
        ]
        report_payload = {
            "fy": "2024-25",
            "stcg_total": "5000.00",
            "ltcg_total": "80000.00",
            "rows": [
                {
                    "security_id": 10,
                    "name": "HDFC Top 100 Fund",
                    "isin": "INF179K01BE2",
                    "units": "100.000",
                    "sale_value": "100000.00",
                    "cost": "20000.00",
                    "gain": "80000.00",
                    "term": "long",
                    "acquired_on": "2020-01-10",
                    "sold_on": "2024-05-15",
                    "grandfathering_unavailable": False,
                }
            ],
            "disclaimer": "Tax draft worksheet",
        }

        with respx.mock(base_url=BASE_URL) as respx_mock:
            respx_mock.get("/api/investors/1/reports/capital-gains-by-fy").respond(
                200, json=by_fy_payload
            )
            respx_mock.get("/api/investors/1/exports/capital-gains").respond(
                200, json=report_payload
            )

            fy_points = await client.capital_gains.list(1)
            assert len(fy_points) == 2
            assert fy_points[1].fy == "2024-25"
            assert fy_points[1].ltcg == Decimal("80000.00")

            report = await client.capital_gains.get(1, fy="2024-25")
            assert isinstance(report, CapitalGainsReport)
            assert report.fy == "2024-25"
            assert report.ltcg_total == Decimal("80000.00")
            assert len(report.rows) == 1
            assert report.rows[0].gain == Decimal("80000.00")


@pytest.mark.asyncio
async def test_client_from_env_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOLIOMAN_BASE_URL", "http://env-folioman:8000")
    monkeypatch.setenv("FOLIOMAN_USERNAME", "env_user")
    monkeypatch.setenv("FOLIOMAN_PASSWORD", "env_password")
    monkeypatch.setenv("FOLIOMAN_TIMEOUT", "45.0")

    client = FoliomanClient.from_env()
    assert client.base_url == "http://env-folioman:8000"
    assert client.username == "env_user"
    assert client.password == "env_password"
    assert client.timeout == 45.0
    await client.close()


@pytest.mark.asyncio
async def test_client_auth_failure_on_retry_raises_auth_error() -> None:
    async with FoliomanClient(
        base_url=BASE_URL,
        username="test_user",
        password="test_password",
    ) as client:
        client._auth._access_token = create_mock_jwt(time.time() + 3600)
        client._auth._refresh_token = create_mock_jwt(time.time() + 86400)

        with respx.mock(base_url=BASE_URL) as respx_mock:
            # First attempt: 401
            respx_mock.get("/api/investors/1").respond(
                401, json={"detail": "Expired token"}
            )
            # Refresh fails: 401
            respx_mock.post("/api/auth/token/refresh").respond(
                401, json={"detail": "Refresh rejected"}
            )
            # Re-auth also fails: 401
            respx_mock.post("/api/auth/token/pair").respond(
                401, json={"detail": "Invalid credentials"}
            )

            with pytest.raises(FoliomanAuthError):
                await client.investors.get(1)
