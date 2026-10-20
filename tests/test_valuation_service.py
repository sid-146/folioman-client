"""Unit and integration tests for ValuationService."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from folioman_client.core.models import TransactionType
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AppliedCorporateAction,
    Family,
    Folio,
    Investor,
    InvestorValue,
    NAVHistory,
    Security,
    Transaction,
)
from folioman_client.services.valuation_service import ValuationService


@pytest.fixture
async def async_engine():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(async_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(async_engine)


@pytest.fixture
def valuation_service(
    async_engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> ValuationService:
    return ValuationService(engine=async_engine, session_factory=session_factory)


@pytest.mark.asyncio
async def test_build_investor_summary_mark_to_market(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        inv = Investor(name="Rohan Sharma", email="rohan@example.com")
        session.add(inv)
        await session.flush()

        sec_mf = Security(
            name="HDFC Top 100 Fund",
            isin="INF179K01BE2",
            security_type="mf",
            amfi_code="101010",
            metadata_json={"amc": "HDFC Mutual Fund", "equity_oriented": True},
        )
        sec_eq = Security(
            name="Infosys Ltd",
            isin="INE009A01021",
            symbol="INFY",
            security_type="equity",
            metadata_json={"category": "Large Cap"},
        )
        session.add_all([sec_mf, sec_eq])
        await session.flush()

        folio = Folio(investor_id=inv.id, number="FOLIO101", broker="Zerodha")
        session.add(folio)
        await session.flush()

        # Buy MF: 100 units @ 50 on 2024-01-01
        t1 = Transaction(
            investor_id=inv.id,
            security_id=sec_mf.id,
            folio_id=folio.id,
            date=date(2024, 1, 1),
            transaction_type=TransactionType.BUY.value,
            units=Decimal(100),
            nav_or_price=Decimal(50),
            amount=Decimal(5000),
            cost_basis_complete=True,
        )
        # Buy Equity: 10 shares @ 1500 on 2024-01-01
        t2 = Transaction(
            investor_id=inv.id,
            security_id=sec_eq.id,
            folio_id=folio.id,
            date=date(2024, 1, 1),
            transaction_type=TransactionType.BUY.value,
            units=Decimal(10),
            nav_or_price=Decimal(1500),
            amount=Decimal(15000),
            cost_basis_complete=True,
        )
        session.add_all([t1, t2])

        # NAV history
        n1 = NAVHistory(security_id=sec_mf.id, date=date(2024, 1, 1), nav=Decimal(50))
        n2 = NAVHistory(security_id=sec_mf.id, date=date(2024, 6, 1), nav=Decimal(60))
        n3 = NAVHistory(security_id=sec_eq.id, date=date(2024, 1, 1), nav=Decimal(1500))
        n4 = NAVHistory(security_id=sec_eq.id, date=date(2024, 6, 1), nav=Decimal(1600))
        session.add_all([n1, n2, n3, n4])
        await session.commit()

        inv_id = inv.id

    summary = await valuation_service.build_investor_summary(
        inv_id, as_of=date(2024, 6, 1)
    )

    # MF value: 100 * 60 = 6000. EQ value: 10 * 1600 = 16000. Total: 22000.
    assert summary["total_inr"] == Decimal(22000)
    assert summary["holdings_count"] == 2
    assert summary["day_change_inr"] is not None
    assert summary["xirr"] is not None
    assert summary["xirr"] > 0

    # Allocation check
    asset_types = {am["security_type"]: am["value_inr"] for am in summary["asset_mix"]}
    assert asset_types["mf"] == Decimal(6000)
    assert asset_types["equity"] == Decimal(16000)


@pytest.mark.asyncio
async def test_build_family_summary_aggregation(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        fam = Family(name="Sharma Family")
        session.add(fam)
        await session.flush()

        inv1 = Investor(name="Rohan", family_id=fam.id)
        inv2 = Investor(name="Pooja", family_id=fam.id)
        session.add_all([inv1, inv2])
        await session.flush()

        sec = Security(name="HDFC Liquid Fund", isin="INF179K01LQ1", security_type="mf")
        session.add(sec)
        await session.flush()

        fol1 = Folio(investor_id=inv1.id, number="F1")
        fol2 = Folio(investor_id=inv2.id, number="F2")
        session.add_all([fol1, fol2])
        await session.flush()

        # Inv1 has 50 units, Inv2 has 50 units @ 100
        t1 = Transaction(
            investor_id=inv1.id,
            security_id=sec.id,
            folio_id=fol1.id,
            date=date(2024, 1, 1),
            transaction_type="buy",
            units=Decimal(50),
            nav_or_price=Decimal(100),
            cost_basis_complete=True,
        )
        t2 = Transaction(
            investor_id=inv2.id,
            security_id=sec.id,
            folio_id=fol2.id,
            date=date(2024, 1, 1),
            transaction_type="buy",
            units=Decimal(50),
            nav_or_price=Decimal(100),
            cost_basis_complete=True,
        )
        session.add_all([t1, t2])
        session.add(
            NAVHistory(security_id=sec.id, date=date(2024, 1, 1), nav=Decimal(100))
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2024, 5, 1), nav=Decimal(110))
        )
        await session.commit()
        fam_id = fam.id

    fam_sum = await valuation_service.build_family_summary(
        fam_id, as_of=date(2024, 5, 1)
    )
    assert fam_sum["investor_count"] == 2
    assert fam_sum["folio_count"] == 2
    # Total units = 100 * 110 = 11000
    assert fam_sum["total_inr"] == Decimal(11000)


@pytest.mark.asyncio
async def test_build_scheme_detail_with_corporate_actions(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        inv = Investor(name="Trader")
        session.add(inv)
        await session.flush()

        sec = Security(name="Tata Steel", symbol="TATASTEEL", security_type="equity")
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="FOLIO_TS")
        session.add(fol)
        await session.flush()

        # Buy 100 shares @ 1000 on 2022-01-01
        session.add(
            Transaction(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                date=date(2022, 1, 1),
                transaction_type="buy",
                units=Decimal(100),
                nav_or_price=Decimal(1000),
                cost_basis_complete=True,
            )
        )
        # Split 1:10 on 2022-07-28
        session.add(
            AppliedCorporateAction(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                kind="split",
                ex_date=date(2022, 7, 28),
                unit_multiplier=Decimal(10),
            )
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2022, 1, 1), nav=Decimal(1000))
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2022, 8, 1), nav=Decimal(110))
        )
        await session.commit()
        inv_id, sec_id = inv.id, sec.id

    detail = await valuation_service.build_scheme_detail(
        inv_id, sec_id, as_of=date(2022, 8, 1)
    )

    # After 1:10 split, units held = 1000
    assert detail["units"] == Decimal(1000)
    # Value = 1000 * 110 = 110,000
    assert detail["value_inr"] == Decimal(110000)
    assert len(detail["corporate_actions"]) == 1
    assert detail["corporate_actions"][0]["kind"] == "split"


@pytest.mark.asyncio
async def test_recompute_investor_valuation_daily_series(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        inv = Investor(name="Series Test", valuation_status="pending")
        session.add(inv)
        await session.flush()

        sec = Security(
            name="Fund Alpha",
            security_type="mf",
            isin="INF123456789",
            amfi_code="100001",
        )
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="F_SERIES")
        session.add(fol)
        await session.flush()

        session.add(
            Transaction(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                date=date(2025, 1, 1),
                transaction_type="buy",
                units=Decimal(100),
                nav_or_price=Decimal(10),
                amount=Decimal(1000),
                cost_basis_complete=True,
            )
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2025, 1, 1), nav=Decimal(10))
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2025, 1, 10), nav=Decimal(12))
        )
        await session.commit()
        inv_id = inv.id

    status = await valuation_service.recompute_investor_valuation(
        inv_id, from_date=date(2025, 1, 1), prime_navs=False
    )
    if status != "ready":
        async with session_factory() as session:
            err = (
                await session.execute(
                    select(Investor.valuation_error).where(Investor.id == inv_id)
                )
            ).scalar()
            print("VALUATION ERROR:", err)
    assert status == "ready"

    async with session_factory() as session:
        stmt_vals = (
            select(InvestorValue)
            .where(InvestorValue.investor_id == inv_id)
            .order_by(InvestorValue.date)
        )
        vals = (await session.execute(stmt_vals)).scalars().all()
        # Verify daily contiguous rows
        assert len(vals) >= 10
        val_map = {v.date: v.value_inr for v in vals}
        assert val_map[date(2025, 1, 1)] == Decimal(1000)
        # On 2025-01-05 carried forward NAV is 10 -> 1000
        assert val_map[date(2025, 1, 5)] == Decimal(1000)
        # On 2025-01-10 NAV is 12 -> 1200
        assert val_map[date(2025, 1, 10)] == Decimal(1200)


@pytest.mark.asyncio
async def test_provisional_value_seeding_and_superseding(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        inv = Investor(name="Provisional Test")
        session.add(inv)
        await session.commit()
        inv_id = inv.id

    # Queue recompute with provisional value
    await valuation_service.queue_recompute(
        inv_id,
        recompute_from=date(2024, 1, 1),
        provisional_value=Decimal(50000),
        provisional_invested=Decimal(40000),
        as_of=date(2024, 1, 1),
    )

    st = await valuation_service.get_valuation_status(inv_id)
    assert st["status"] == "computing"
    assert st["is_provisional"] is True

    # Recompute supersedes provisional row
    async with session_factory() as session:
        sec = Security(
            name="Fund Beta",
            security_type="mf",
            isin="INF987654321",
            amfi_code="100002",
        )
        session.add(sec)
        await session.flush()
        fol = Folio(investor_id=inv_id, number="F_BETA")
        session.add(fol)
        await session.flush()
        session.add(
            Transaction(
                investor_id=inv_id,
                security_id=sec.id,
                folio_id=fol.id,
                date=date(2024, 1, 1),
                transaction_type="buy",
                units=Decimal(100),
                nav_or_price=Decimal(100),
                amount=Decimal(10000),
                cost_basis_complete=True,
            )
        )
        session.add(
            NAVHistory(security_id=sec.id, date=date(2024, 1, 1), nav=Decimal(100))
        )
        await session.commit()

    await valuation_service.recompute_investor_valuation(
        inv_id, from_date=date(2024, 1, 1), prime_navs=False
    )

    st2 = await valuation_service.get_valuation_status(inv_id)
    assert st2["status"] == "ready"
    assert st2["is_provisional"] is False


@pytest.mark.asyncio
async def test_enqueue_daily_extend_and_ticks(
    session_factory: async_sessionmaker[AsyncSession],
    valuation_service: ValuationService,
):
    async with session_factory() as session:
        inv1 = Investor(
            name="Ready Investor",
            valuation_status="ready",
            valuation_computed_through=date(2024, 1, 1),
        )
        inv2 = Investor(
            name="Error Investor", valuation_status="error", valuation_attempts=3
        )
        session.add_all([inv1, inv2])
        await session.commit()

    cnt = await valuation_service.enqueue_daily_extend()
    assert cnt == 2

    async with session_factory() as session:
        stmt = select(Investor.valuation_status, Investor.valuation_recompute_from)
        rows = (await session.execute(stmt)).all()
        for status, recompute_from in rows:
            assert status == "pending"
