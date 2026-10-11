"""Integration tests for NAVService."""

from datetime import date, timedelta
from decimal import Decimal
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from folioman_client.core.models.security import SecurityType
from folioman_client.core.trading_calendar import completed_trading_day
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    Folio,
    Holding,
    Investor,
    NAVHistory,
    Security,
    Transaction,
)
from folioman_client.services.nav_service import NAVService


@pytest.fixture
async def test_engine():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    session_factory = create_sessionmaker(test_engine)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def setup_portfolio(db_session: AsyncSession):
    """Seed test portfolio with mutual funds, equities, and crypto."""
    investor = Investor(
        name="Test Investor",
        pan_encrypted=b"dummy_pan_enc",
        pan_hash="dummy_hash",
        user_id="default",
    )
    db_session.add(investor)
    await db_session.flush()

    folio = Folio(
        investor_id=investor.id,
        number="12345/0",
        amc_code="PPFAS",
    )
    db_session.add(folio)
    await db_session.flush()

    # MF 1: Parag Parikh Flexi Cap
    sec_mf = Security(
        security_type=SecurityType.MF.value,
        name="Parag Parikh Flexi Cap Fund",
        isin="INF879O01019",
        amfi_code="122639",
    )
    # MF 2: Dead / delisted fund
    sec_dead = Security(
        security_type=SecurityType.MF.value,
        name="Matured Closed Scheme",
        isin="INF000K00000",
        amfi_code="999999",
    )
    # Equity: TCS
    sec_eq = Security(
        security_type=SecurityType.EQUITY.value,
        name="Tata Consultancy Services",
        isin="INE467B01029",
        symbol="TCS",
        exchange="NSE",
    )
    # Crypto: Bitcoin
    sec_crypto = Security(
        security_type=SecurityType.CRYPTO.value,
        name="Bitcoin",
        metadata_json={"coin_id": "bitcoin"},
    )
    # No feed: FD
    sec_fd = Security(
        security_type=SecurityType.FD.value,
        name="HDFC Fixed Deposit",
    )

    db_session.add_all([sec_mf, sec_dead, sec_eq, sec_crypto, sec_fd])
    await db_session.flush()

    # Add transaction for MF
    txn_mf = Transaction(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec_mf.id,
        date=date(2026, 4, 1),
        transaction_type="BUY",
        units=Decimal("100.000"),
        nav_or_price=Decimal("70.0000"),
        amount=Decimal("7000.00"),
        dedup_key="txn_1",
    )
    # Add holding for Equity
    hold_eq = Holding(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec_eq.id,
        as_of_date=date(2026, 4, 1),
        units=Decimal("10.000"),
        value_observed=Decimal("35000.00"),
    )
    db_session.add_all([txn_mf, hold_eq])
    await db_session.commit()

    return {
        "investor": investor,
        "sec_mf": sec_mf,
        "sec_dead": sec_dead,
        "sec_eq": sec_eq,
        "sec_crypto": sec_crypto,
        "sec_fd": sec_fd,
    }


@pytest.mark.asyncio
async def test_refresh_navs_with_bulk_and_fallback(test_engine, setup_portfolio):
    svc = NAVService(engine=test_engine, request_spacing=0.0)
    data = setup_portfolio

    # Mock bulk AMFI and fallbacks
    with respx.mock(assert_all_mocked=False) as rmock:
        # 1. AMFI bulk NAVAll containing sec_mf
        rmock.get("https://portal.amfiindia.com/spages/NAVAll.txt").respond(
            200,
            text=(
                "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
                "122639;INF879O01019;INF879O01027;Parag Parikh Flexi Cap;75.5000;10-Apr-2026\n"
            ),
        )
        # 2. Bhavcopy fails (empty) so equity falls back to Yahoo
        rmock.get(url__regex=r"^https://nsearchives\.nseindia\.com/.*").respond(404)
        rmock.get(url__regex=r"^https://www\.nseindia\.com/.*").respond(404)

        # 3. Yahoo chart for TCS.NS
        rmock.get("https://query1.finance.yahoo.com/v8/finance/chart/TCS.NS").respond(
            200,
            json={
                "chart": {
                    "result": [
                        {"meta": {"regularMarketPrice": 3900.0, "currency": "INR"}}
                    ],
                    "error": None,
                }
            },
        )

        # 4. CoinGecko for Bitcoin
        rmock.get("https://api.coingecko.com/api/v3/simple/price").respond(
            200,
            json={"bitcoin": {"inr": 8600000.0}},
        )

        # 5. Dead MF returns 404
        rmock.get("https://api.mfapi.in/mf/999999/latest").respond(404)
        rmock.get("https://mf.captnemo.in/nav/INF000K00000").respond(404)

        summary = await svc.refresh_navs()
        assert summary["updated"] == 3  # MF, Equity, Crypto updated
        assert summary["errors"] == 1  # sec_dead 404 is caught and isolated

        # Verify DB rows
        async with svc.session_factory() as session:
            # Check MF NAV
            mf_nav = (
                await session.execute(
                    select(NAVHistory).where(
                        NAVHistory.security_id == data["sec_mf"].id
                    )
                )
            ).scalar_one_or_none()
            assert mf_nav is not None
            assert mf_nav.nav == Decimal("75.500000")
            assert mf_nav.source == "amfi"

            # Check Equity price
            eq_nav = (
                await session.execute(
                    select(NAVHistory).where(
                        NAVHistory.security_id == data["sec_eq"].id
                    )
                )
            ).scalar_one_or_none()
            assert eq_nav is not None
            assert eq_nav.nav == Decimal("3900.000000")
            assert eq_nav.source == "yfinance"


@pytest.mark.asyncio
async def test_backfill_navs_and_closed_feed_marking(test_engine, setup_portfolio):
    svc = NAVService(engine=test_engine, request_spacing=0.0)
    data = setup_portfolio

    with (
        respx.mock(base_url="https://mf.captnemo.in") as captnemo_mock,
        respx.mock(base_url="https://api.mfapi.in") as mfapi_mock,
    ):
        # MF history
        captnemo_mock.get("/nav/INF879O01019").respond(
            200,
            json={
                "ISIN": "INF879O01019",
                "name": "Parag Parikh Flexi Cap",
                "historical_nav": [
                    ["2026-04-01", 70.0000],
                    ["2026-04-02", 71.0000],
                    ["2026-04-03", 72.0000],
                ],
            },
        )
        # Dead fund responds with 404
        captnemo_mock.get("/nav/INF000K00000").respond(404)
        mfapi_mock.get("/mf/999999").respond(
            200,
            json={"meta": {}, "data": [], "status": "SUCCESS"},
        )

        summary = await svc.backfill_navs(security_id=data["sec_mf"].id)
        assert summary["points"] == 3
        assert summary["securities"] == 1

        # Second backfill should be idempotent (0 new points)
        summary2 = await svc.backfill_navs(security_id=data["sec_mf"].id)
        assert summary2["points"] == 0

        # Backfill dead scheme -> marks nav_feed_closed
        dead_summary = await svc.backfill_navs(
            security_id=data["sec_dead"].id, force=True
        )
        assert dead_summary["closed"] == 1

        async with svc.session_factory() as session:
            refreshed_dead = (
                await session.execute(
                    select(Security).where(Security.id == data["sec_dead"].id)
                )
            ).scalar_one()
            assert refreshed_dead.nav_feed_closed is True


@pytest.mark.asyncio
async def test_nav_freshness_classification(test_engine, setup_portfolio):
    svc = NAVService(engine=test_engine)
    data = setup_portfolio
    cutoff = completed_trading_day(date.today())

    # Add a fresh NAV for sec_mf (on cutoff)
    async with svc.session_factory() as session:
        session.add(
            NAVHistory(
                security_id=data["sec_mf"].id,
                date=cutoff,
                nav=Decimal("75.0000"),
                source="test",
            )
        )
        await session.commit()

    freshness = await svc.get_nav_freshness(investor_ids=[data["investor"].id])
    assert freshness["as_of"] == cutoff
    assert len(freshness["securities"]) == 2  # sec_mf and sec_eq are in portfolio

    sec_map = {s["security_id"]: s for s in freshness["securities"]}
    # sec_mf has NAV on cutoff -> fresh
    assert sec_map[data["sec_mf"].id]["status"] == "fresh"
    assert sec_map[data["sec_mf"].id]["lag_trading_days"] == 0

    # sec_eq has no NAV yet -> pending
    assert sec_map[data["sec_eq"].id]["status"] == "pending"
    assert sec_map[data["sec_eq"].id]["latest_nav_date"] is None
