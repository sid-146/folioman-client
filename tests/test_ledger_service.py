"""Unit tests for LedgerService: investor profiles, folios, manual transactions, and opening lots."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import Family, Security
from folioman_client.services.ledger_service import LedgerService


@pytest.fixture
async def ledger_service():
    """Provides a LedgerService instance backed by an isolated in-memory SQLite database."""
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = LedgerService(engine=engine)
    yield service
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_get_investor(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(
        user_id="advisor_1",
        name="Sunil Gavaskar",
        pan="ABCDE1234F",
        email="sunil@example.com",
    )
    assert inv["name"] == "Sunil Gavaskar"
    assert inv["pan_masked"] == "XXXXXX234F"
    assert inv["has_pan"] is True

    fetched = await ledger_service.get_investor(inv["id"])
    assert fetched["id"] == inv["id"]
    assert fetched["name"] == "Sunil Gavaskar"
    assert fetched["pan_masked"] == "XXXXXX234F"


@pytest.mark.asyncio
async def test_list_investors_filtering(ledger_service: LedgerService):
    async with ledger_service.session_factory() as session:
        family = Family(name="Test Family", user_id="advisor_1")
        session.add(family)
        await session.commit()
        fam_id = family.id

    inv1 = await ledger_service.create_investor(
        user_id="advisor_1", name="Alice", family_id=fam_id
    )
    inv2 = await ledger_service.create_investor(
        user_id="advisor_1", name="Bob", family_id=fam_id
    )
    inv3 = await ledger_service.create_investor(
        user_id="advisor_1", name="Charlie", family_id=None
    )
    inv_other = await ledger_service.create_investor(user_id="advisor_2", name="Dave")

    all_adv1 = await ledger_service.list_investors(user_id="advisor_1")
    assert len(all_adv1) == 3

    family_filtered = await ledger_service.list_investors(
        user_id="advisor_1", family_id=fam_id
    )
    assert len(family_filtered) == 2
    assert {i["name"] for i in family_filtered} == {"Alice", "Bob"}

    unaffiliated = await ledger_service.list_investors(
        user_id="advisor_1", unaffiliated=True
    )
    assert len(unaffiliated) == 1
    assert unaffiliated[0]["name"] == "Charlie"


@pytest.mark.asyncio
async def test_create_and_list_folios(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(name="Rahul Dravid")
    f1 = await ledger_service.create_folio(
        inv["id"], " 12345/6 ", amc_code="HDFC", folio_type="mf"
    )
    # Folio number should be normalized
    assert f1["number"] == "12345/6"
    assert f1["amc_code"] == "HDFC"

    # Creating identical folio should return existing
    f1_dup = await ledger_service.create_folio(inv["id"], "12345/6", amc_code="HDFC")
    assert f1_dup["id"] == f1["id"]

    f2 = await ledger_service.create_folio(
        inv["id"], "IN300126-10203040", broker="ZERODHA", folio_type="demat"
    )

    folios = await ledger_service.list_folios(inv["id"])
    assert len(folios) == 2
    assert {f["number"] for f in folios} == {"12345/6", "IN300126-10203040"}


@pytest.mark.asyncio
async def test_create_transaction_and_listing(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(name="Sachin Tendulkar")
    fol = await ledger_service.create_folio(inv["id"], "1001", amc_code="SBI")

    async with ledger_service.session_factory() as session:
        sec = Security(
            name="SBI Bluechip Fund - Direct - Growth",
            isin="INF200K01123",
            security_type="MF",
        )
        session.add(sec)
        await session.commit()
        sec_id = sec.id

    # Create Buy Transaction
    tx1 = await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec_id,
        folio_id=fol["id"],
        date=date(2025, 1, 15),
        transaction_type="BUY",
        units=Decimal(100),
        nav_or_price=Decimal("50.0"),
        fees=Decimal("0.5"),
    )
    assert tx1["units"] == "100"
    assert tx1["amount"] == "5000.0"

    # Create Sell Transaction
    tx2 = await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec_id,
        folio_id=fol["id"],
        date=date(2025, 6, 20),
        transaction_type="SELL",
        units=Decimal(40),
        nav_or_price=Decimal("60.0"),
    )

    txns = await ledger_service.list_transactions(inv["id"], security_id=sec_id)
    assert len(txns) == 2
    assert txns[0]["type"] == "BUY"
    assert txns[1]["type"] == "SELL"

    # Filter by date range
    filtered = await ledger_service.list_transactions(
        inv["id"], from_date=date(2025, 6, 1)
    )
    assert len(filtered) == 1
    assert filtered[0]["type"] == "SELL"


@pytest.mark.asyncio
async def test_create_opening_lot(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(name="Sourav Ganguly")
    fol = await ledger_service.create_folio(
        inv["id"], "12081600-00112233", folio_type="demat"
    )

    async with ledger_service.session_factory() as session:
        sec = Security(
            name="Tata Motors Ltd",
            isin="INE155A01022",
            symbol="TATAMOTORS",
            security_type="EQUITY",
        )
        session.add(sec)
        await session.commit()
        sec_id = sec.id

    op_lot = await ledger_service.create_opening_lot(
        investor_id=inv["id"],
        folio_id=fol["id"],
        security_id=sec_id,
        units=Decimal(50),
        cost_basis=Decimal(25000),
        as_of_date=date(2024, 3, 1),
        classification="ipo_allotment",
    )
    assert op_lot["units"] == "50"
    assert op_lot["nav_or_price"] == "500"
    assert op_lot["amount"] == "25000"

    txns = await ledger_service.list_transactions(inv["id"])
    assert len(txns) == 1
    assert txns[0]["source_ref"] == f"opening-lot:{fol['id']}:{sec_id}:ipo_allotment"
    assert "Opening lot" in txns[0]["narration"]


@pytest.mark.asyncio
async def test_merge_folios(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(name="VVS Laxman")
    f_source = await ledger_service.create_folio(inv["id"], "999/0", amc_code="UTI")
    f_target = await ledger_service.create_folio(inv["id"], "999/1", amc_code="UTI")

    async with ledger_service.session_factory() as session:
        sec = Security(
            name="UTI Nifty 50 Index Fund", isin="INF789F01010", security_type="MF"
        )
        session.add(sec)
        await session.commit()
        sec_id = sec.id

    # Add transaction to source folio
    await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec_id,
        folio_id=f_source["id"],
        date=date(2025, 2, 1),
        transaction_type="BUY",
        units=Decimal(75),
        nav_or_price=Decimal(120),
    )

    # Merge source into target
    merge_res = await ledger_service.merge_folios(
        investor_id=inv["id"],
        source_folio_id=f_source["id"],
        target_folio_id=f_target["id"],
    )
    assert merge_res["transactions_moved"] == 1

    # Source folio should be deleted
    remaining_folios = await ledger_service.list_folios(inv["id"])
    assert len(remaining_folios) == 1
    assert remaining_folios[0]["id"] == f_target["id"]

    # Transaction should now belong to target folio
    txns = await ledger_service.list_transactions(inv["id"], folio_id=f_target["id"])
    assert len(txns) == 1
    assert txns[0]["folio_id"] == f_target["id"]


@pytest.mark.asyncio
async def test_list_holdings_active_positions(ledger_service: LedgerService):
    inv = await ledger_service.create_investor(name="Jasprit Bumrah")
    fol = await ledger_service.create_folio(inv["id"], "FOLIO-1")

    async with ledger_service.session_factory() as session:
        sec1 = Security(name="Active Fund", isin="INF111A01011", security_type="MF")
        sec2 = Security(name="Closed Fund", isin="INF222B01022", security_type="MF")
        session.add_all([sec1, sec2])
        await session.commit()
        sec1_id, sec2_id = sec1.id, sec2.id

    # sec1 has net positive units (100 buy - 30 sell = 70)
    await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec1_id,
        folio_id=fol["id"],
        date=date(2025, 1, 1),
        transaction_type="BUY",
        units=Decimal(100),
        nav_or_price=Decimal(10),
    )
    await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec1_id,
        folio_id=fol["id"],
        date=date(2025, 2, 1),
        transaction_type="SELL",
        units=Decimal(30),
        nav_or_price=Decimal(12),
    )

    # sec2 has net zero units (50 buy - 50 sell = 0)
    await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec2_id,
        folio_id=fol["id"],
        date=date(2025, 1, 1),
        transaction_type="BUY",
        units=Decimal(50),
        nav_or_price=Decimal(20),
    )
    await ledger_service.create_transaction(
        investor_id=inv["id"],
        security_id=sec2_id,
        folio_id=fol["id"],
        date=date(2025, 2, 1),
        transaction_type="SELL",
        units=Decimal(50),
        nav_or_price=Decimal(22),
    )

    holdings = await ledger_service.list_holdings(inv["id"])
    assert len(holdings) == 1
    assert holdings[0]["security_id"] == sec1_id
    assert Decimal(holdings[0]["units"]) == Decimal(70)
