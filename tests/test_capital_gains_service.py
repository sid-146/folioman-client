"""Unit and integration tests for CapitalGainsService."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from folioman_client.core.reconciliation import IntegrityStatus
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    Folio,
    GrandfatheringNAV,
    Investor,
    NAVHistory,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)
from folioman_client.services.capital_gains_service import CapitalGainsService


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
def capital_gains_service(
    async_engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> CapitalGainsService:
    return CapitalGainsService(engine=async_engine, session_factory=session_factory)


@pytest.mark.asyncio
async def test_stcg_and_ltcg_segregation_and_tie_out(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Taxpayer A")
        session.add(inv)
        await session.flush()

        sec_mf = Security(
            name="Nippon India Large Cap Fund",
            isin="INF204K01XX1",
            amfi_code="102030",
            security_type="mf",
            metadata_json={"equity_oriented": True},
        )
        session.add(sec_mf)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="FOL_TAX_1")
        session.add(fol)
        await session.flush()

        # Mark folio as reconciled
        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec_mf.id,
                folio_id=fol.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )

        # Lot 1 (LTCG): bought 2022-01-01, 100 units @ 100
        t1 = Transaction(
            investor_id=inv.id,
            security_id=sec_mf.id,
            folio_id=fol.id,
            date=date(2022, 1, 1),
            transaction_type="buy",
            units=Decimal("100"),
            nav_or_price=Decimal("100"),
            amount=Decimal("10000"),
            cost_basis_complete=True,
        )
        # Lot 2 (STCG): bought 2024-01-01, 50 units @ 120
        t2 = Transaction(
            investor_id=inv.id,
            security_id=sec_mf.id,
            folio_id=fol.id,
            date=date(2024, 1, 1),
            transaction_type="buy",
            units=Decimal("50"),
            nav_or_price=Decimal("120"),
            amount=Decimal("6000"),
            cost_basis_complete=True,
        )
        # Sale 1 (LTCG disposal in FY 2024-25): sold 50 units @ 150 on 2024-05-10
        t3 = Transaction(
            investor_id=inv.id,
            security_id=sec_mf.id,
            folio_id=fol.id,
            date=date(2024, 5, 10),
            transaction_type="redemption",
            units=Decimal("50"),
            nav_or_price=Decimal("150"),
            amount=Decimal("7500"),
            cost_basis_complete=True,
        )
        # Sale 2 (STCG disposal in FY 2024-25): bought on 2024-01-01, sold on 2024-08-15 (after depleting first 100 units)
        # To sell from Lot 2, sell another 60 units (50 from Lot 1 @ 100 cost, 10 from Lot 2 @ 120 cost)
        t4 = Transaction(
            investor_id=inv.id,
            security_id=sec_mf.id,
            folio_id=fol.id,
            date=date(2024, 8, 15),
            transaction_type="redemption",
            units=Decimal("60"),
            nav_or_price=Decimal("160"),
            amount=Decimal("9600"),
            cost_basis_complete=True,
        )
        session.add_all([t1, t2, t3, t4])
        await session.commit()
        inv_id = inv.id

    report = await capital_gains_service.get_capital_gains_report(inv_id, "2024-25")
    assert report["fy"] == "2024-25"
    assert len(report["rows"]) == 3

    # Tie-out check: cost = sale_value - gain
    for row in report["rows"]:
        assert row["cost"] == row["sale_value"] - row["gain"]

    # LTCG:
    # 1. 50 units sold @ 150 (cost 100) -> gain = 50 * 50 = 2500
    # 2. 50 units sold @ 160 (cost 100) -> gain = 50 * 60 = 3000
    # Total LTCG = 5500
    assert report["ltcg_total"] == Decimal("5500.00")

    # STCG:
    # 10 units sold @ 160 (cost 120) -> gain = 10 * 40 = 400
    # Total STCG = 400
    assert report["stcg_total"] == Decimal("400.00")


@pytest.mark.asyncio
async def test_section_112a_grandfathering_with_seeded_fmv(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Grandfathered Investor")
        session.add(inv)
        await session.flush()

        sec = Security(
            name="HDFC Flexi Cap Fund",
            isin="INF179K01999",
            amfi_code="105555",
            security_type="mf",
            metadata_json={"equity_oriented": True},
        )
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="FOL_GF")
        session.add(fol)
        await session.flush()

        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )

        # Seed GrandfatheringNAV for 2018-01-31
        session.add(
            GrandfatheringNAV(
                isin="INF179K01999",
                nav=Decimal("250.00"),
            )
        )

        # Bought pre-2018: 100 units @ 100 on 2016-03-15
        t_buy = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2016, 3, 15),
            transaction_type="buy",
            units=Decimal("100"),
            nav_or_price=Decimal("100"),
            amount=Decimal("10000"),
            cost_basis_complete=True,
        )
        # Sold post-2018 in FY 2024-25: 100 units @ 400 on 2024-07-20
        t_sell = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2024, 7, 20),
            transaction_type="redemption",
            units=Decimal("100"),
            nav_or_price=Decimal("400"),
            amount=Decimal("40000"),
            cost_basis_complete=True,
        )
        session.add_all([t_buy, t_sell])
        await session.commit()
        inv_id = inv.id

    report = await capital_gains_service.get_capital_gains_report(inv_id, "2024-25")
    assert len(report["rows"]) == 1
    row = report["rows"][0]

    # Section 112A Grandfathering formula:
    # Actual cost = 100 * 100 = 10,000
    # FMV on 2018-01-31 = 100 * 250 = 25,000
    # Sale value = 100 * 400 = 40,000
    # Grandfathered cost = max(actual_cost, min(sale_value, total_fmv)) = max(10000, min(40000, 25000)) = 25000
    # Taxable LTCG = 40,000 - 25,000 = 15,000 (rather than 30,000 without grandfathering)
    assert row["cost"] == Decimal("25000.00")
    assert row["gain"] == Decimal("15000.00")
    assert row["grandfathering_unavailable"] is False


@pytest.mark.asyncio
async def test_grandfathering_unavailable_fallback(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Unknown FMV Investor")
        session.add(inv)
        await session.flush()

        sec = Security(
            name="Unlisted Vintage Stock",
            isin="INE999UNKNW1",
            security_type="equity",
            metadata_json={"equity_oriented": True},
        )
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="FOL_NO_FMV")
        session.add(fol)
        await session.flush()

        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )

        # Bought pre-2018: 50 units @ 200 on 2015-05-10
        t_buy = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2015, 5, 10),
            transaction_type="buy",
            units=Decimal("50"),
            nav_or_price=Decimal("200"),
            amount=Decimal("10000"),
            cost_basis_complete=True,
        )
        # Sold in FY 2024-25: 50 units @ 500 on 2024-09-10
        t_sell = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2024, 9, 10),
            transaction_type="sell",
            units=Decimal("50"),
            nav_or_price=Decimal("500"),
            amount=Decimal("25000"),
            cost_basis_complete=True,
        )
        session.add_all([t_buy, t_sell])
        await session.commit()
        inv_id = inv.id

    # No FMV anywhere
    report = await capital_gains_service.get_capital_gains_report(inv_id, "2024-25")
    assert len(report["rows"]) == 1
    row = report["rows"][0]

    # Falls back to actual cost 50 * 200 = 10,000
    assert row["cost"] == Decimal("10000.00")
    assert row["gain"] == Decimal("15000.00")
    assert row["grandfathering_unavailable"] is True


@pytest.mark.asyncio
async def test_tax_readiness_integrity_gating(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Integrity Gate Investor")
        session.add(inv)
        await session.flush()

        sec = Security(name="Fund X", isin="INF101X01010", security_type="mf")
        session.add(sec)
        await session.flush()

        fol_reconciled = Folio(investor_id=inv.id, number="F_REC")
        fol_unreconciled = Folio(investor_id=inv.id, number="F_UNREC")
        fol_snapshot = Folio(investor_id=inv.id, number="F_SNAP")
        session.add_all([fol_reconciled, fol_unreconciled, fol_snapshot])
        await session.flush()

        # Set statuses
        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol_reconciled.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )
        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol_unreconciled.id,
                status=IntegrityStatus.MISMATCH.value,
            )
        )
        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol_snapshot.id,
                status=IntegrityStatus.SNAPSHOT_ONLY.value,
            )
        )

        def add_txns(fol_id):
            return [
                Transaction(
                    investor_id=inv.id,
                    security_id=sec.id,
                    folio_id=fol_id,
                    date=date(2024, 1, 1),
                    transaction_type="buy",
                    units=Decimal("10"),
                    nav_or_price=Decimal("100"),
                    cost_basis_complete=True,
                ),
                Transaction(
                    investor_id=inv.id,
                    security_id=sec.id,
                    folio_id=fol_id,
                    date=date(2024, 6, 1),
                    transaction_type="redemption",
                    units=Decimal("10"),
                    nav_or_price=Decimal("110"),
                    cost_basis_complete=True,
                ),
            ]

        session.add_all(add_txns(fol_reconciled.id))
        session.add_all(add_txns(fol_unreconciled.id))
        session.add_all(add_txns(fol_snapshot.id))
        await session.commit()
        inv_id = inv.id

    # 1. By default, only reconciled is included (1 disposal)
    report_default = await capital_gains_service.get_capital_gains_report(
        inv_id, "2024-25"
    )
    assert len(report_default["rows"]) == 1

    # 2. With include_unreconciled=True, reconciled + unreconciled are included (2 disposals).
    # SNAPSHOT_ONLY is still strictly excluded!
    report_opt_in = await capital_gains_service.get_capital_gains_report(
        inv_id, "2024-25", include_unreconciled=True
    )
    assert len(report_opt_in["rows"]) == 2


@pytest.mark.asyncio
async def test_list_capital_gains_by_fy(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Multi FY Investor")
        session.add(inv)
        await session.flush()

        sec = Security(
            name="Fund Y",
            isin="INF202Y02020",
            security_type="mf",
            metadata_json={"equity_oriented": True},
        )
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="F_MULTI")
        session.add(fol)
        await session.flush()

        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )

        # Buy 100 units on 2022-01-01 @ 100
        t_buy = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2022, 1, 1),
            transaction_type="buy",
            units=Decimal("100"),
            nav_or_price=Decimal("100"),
            cost_basis_complete=True,
        )
        # Sell 50 units in FY 2022-23 (2022-12-01) @ 120 -> LTCG = 50 * 20 = 1000
        t_sell1 = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2022, 12, 1),
            transaction_type="redemption",
            units=Decimal("50"),
            nav_or_price=Decimal("120"),
            cost_basis_complete=True,
        )
        # Sell 50 units in FY 2024-25 (2024-05-01) @ 150 -> LTCG = 50 * 50 = 2500
        t_sell2 = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2024, 5, 1),
            transaction_type="redemption",
            units=Decimal("50"),
            nav_or_price=Decimal("150"),
            cost_basis_complete=True,
        )
        session.add_all([t_buy, t_sell1, t_sell2])
        await session.commit()
        inv_id = inv.id

    fy_list = await capital_gains_service.list_capital_gains_by_fy(inv_id)
    assert len(fy_list) == 2
    fy_map = {item["fy"]: item for item in fy_list}

    assert "2022-23" in fy_map
    assert fy_map["2022-23"]["stcg"] == Decimal("1000.00")

    assert "2024-25" in fy_map
    assert fy_map["2024-25"]["ltcg"] == Decimal("2500.00")


@pytest.mark.asyncio
async def test_get_schedule_112a_export(
    session_factory: async_sessionmaker[AsyncSession],
    capital_gains_service: CapitalGainsService,
):
    async with session_factory() as session:
        inv = Investor(name="Schedule 112A Investor")
        session.add(inv)
        await session.flush()

        sec = Security(
            name="Axis Bluechip Fund",
            isin="INF846K01164",
            amfi_code="112233",
            security_type="mf",
            metadata_json={"equity_oriented": True},
        )
        session.add(sec)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="F_112A")
        session.add(fol)
        await session.flush()

        session.add(
            SecurityIntegrityStatus(
                investor_id=inv.id,
                security_id=sec.id,
                folio_id=fol.id,
                status=IntegrityStatus.RECONCILED.value,
            )
        )

        session.add(
            GrandfatheringNAV(
                isin="INF846K01164",
                nav=Decimal("35.00"),
            )
        )

        # Acquired pre-2018: 1000 units @ 20 on 2017-01-10
        t1 = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2017, 1, 10),
            transaction_type="buy",
            units=Decimal("1000"),
            nav_or_price=Decimal("20"),
            cost_basis_complete=True,
        )
        # Sold in FY 2024-25: 1000 units @ 50 on 2024-06-15
        t2 = Transaction(
            investor_id=inv.id,
            security_id=sec.id,
            folio_id=fol.id,
            date=date(2024, 6, 15),
            transaction_type="redemption",
            units=Decimal("1000"),
            nav_or_price=Decimal("50"),
            cost_basis_complete=True,
        )
        session.add_all([t1, t2])
        await session.commit()
        inv_id = inv.id

    res = await capital_gains_service.get_schedule_112a(inv_id, "2024-25")
    assert res["fy"] == "2024-25"
    assert res["row_count"] == 1
    assert len(res["columns"]) == 15
    assert "ISIN Code(2)" in res["columns"]

    row = res["rows"][0]
    assert row["Share/Unit acquired(1a)"] == "BE"  # Before 2018-02-01
    assert row["Share/Unit Transferred(1b)"] == "BE"  # Before 2024-07-23
    assert row["ISIN Code(2)"] == "INF846K01164"
    assert row["Name of the Share/Unit(3)"] == "Axis Bluechip Fund"
    assert row["No. of Shares/Units(4)"] == "1000"
    assert row["Sale-price per Share/Unit(5)"] == "50"
    assert row["Full Value of Consideration(Total Sale Value)(6) = 4 * 5"] == "50000.00"
    assert row["Cost of acquisition without indexation(7)"] == "35000.00"
    assert row["Fair Market Value per share/unit as on 31st January 2018(10)"] == "35"
    assert row["Balance(14) = 6 - 13"] == "15000.00"
