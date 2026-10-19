"""Tests for SQLAlchemy 2.0 Declarative Models across all 18 tables."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AMC,
    AppliedCorporateAction,
    CorporateActionReference,
    Family,
    Folio,
    FXRate,
    GrandfatheringNAV,
    Holding,
    ImportJob,
    ImportQuarantine,
    Investor,
    InvestorValue,
    ISINReference,
    NAVHistory,
    ReferenceMeta,
    SchemeReference,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)
from folioman_client.security.pan import encrypt_pan, pan_hash


@pytest.fixture
async def db_session():
    """Provides an isolated database session with full schema initialized in-memory."""
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    session_factory = create_sessionmaker(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_reference_master_tables(db_session) -> None:
    # 1. SchemeReference
    scheme = SchemeReference(
        id=1001,
        rta="CAMS",
        rta_code="P8042",
        name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        isin="INF879O01019",
        amfi_code="119551",
        type="Open Ended Schemes",
    )
    db_session.add(scheme)

    # 2. ISINReference
    isin_ref = ISINReference(
        isin="INF879O01019",
        symbol="PPFAS",
        name="Parag Parikh Flexi Cap Fund",
        exchange="NSE",
    )
    db_session.add(isin_ref)

    # 3. GrandfatheringNAV
    gf_nav = GrandfatheringNAV(
        isin="INF879O01019",
        nav=Decimal("28.452000"),
    )
    db_session.add(gf_nav)

    # 4. ReferenceMeta
    meta = ReferenceMeta(key="isin_db_version", value="2026.6.9")
    db_session.add(meta)
    await db_session.commit()

    # Query back & verify
    q_scheme = await db_session.get(SchemeReference, 1001)
    assert q_scheme is not None
    assert q_scheme.amfi_code == "119551"
    assert q_scheme.rta == "CAMS"

    q_isin = await db_session.execute(
        select(ISINReference).where(ISINReference.isin == "INF879O01019")
    )
    assert q_isin.scalar_one().symbol == "PPFAS"

    q_gf = await db_session.execute(
        select(GrandfatheringNAV).where(GrandfatheringNAV.isin == "INF879O01019")
    )
    assert q_gf.scalar_one().nav == Decimal("28.452000")

    q_meta = await db_session.get(ReferenceMeta, "isin_db_version")
    assert q_meta is not None
    assert q_meta.value == "2026.6.9"


@pytest.mark.asyncio
async def test_securities_and_market_data(db_session) -> None:
    # 1. AMC
    amc = AMC(code="PPFAS", name="PPFAS Mutual Fund")
    db_session.add(amc)
    await db_session.commit()

    # 2. Security
    security = Security(
        isin="INF879O01019",
        name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
        security_type="MF",
        amc_id=amc.id,
        amfi_code="119551",
        metadata_json={"asset_class": "Equity"},
    )
    db_session.add(security)
    await db_session.commit()

    # 3. NAVHistory
    nav_entry = NAVHistory(
        security_id=security.id,
        date=date(2026, 3, 1),
        nav=Decimal("78.123400"),
    )
    db_session.add(nav_entry)

    # 4. FXRate
    fx = FXRate(
        base_currency="USD",
        quote_currency="INR",
        date=date(2026, 3, 1),
        rate=Decimal("86.500000"),
    )
    db_session.add(fx)

    # 5. CorporateActionReference
    ca = CorporateActionReference(
        security_id=security.id,
        isin="INF879O01019",
        symbol="PPFAS",
        series="EQ",
        exchange="NSE",
        ex_date=date(2026, 1, 15),
        subject="Stock Split 1:2",
        parsed_type="SPLIT",
        unit_multiplier=Decimal("2.000000"),
    )
    db_session.add(ca)
    await db_session.commit()

    # Assertions
    stmt = select(NAVHistory).where(NAVHistory.security_id == security.id)
    result = await db_session.execute(stmt)
    records = result.scalars().all()
    assert len(records) == 1
    assert records[0].nav == Decimal("78.123400")

    stmt_fx = select(FXRate).where(FXRate.base_currency == "USD")
    res_fx = await db_session.execute(stmt_fx)
    assert res_fx.scalar_one().rate == Decimal("86.500000")


@pytest.mark.asyncio
async def test_portfolio_ledger_and_investor_cascade(db_session) -> None:
    # Setup AMC & Security
    amc = AMC(code="HDFC", name="HDFC Mutual Fund")
    db_session.add(amc)
    await db_session.commit()

    sec = Security(
        isin="INF179K01BE2",
        name="HDFC Top 100 Fund - Direct - Growth",
        security_type="MF",
        amc_id=amc.id,
    )
    db_session.add(sec)

    # Family & Investor
    family = Family(name="Sharma Family", user_id="user_123")
    db_session.add(family)
    await db_session.commit()

    plain_pan = "ABCDE1234F"
    investor = Investor(
        user_id="user_123",
        family_id=family.id,
        name="Raj Sharma",
        email="raj@example.com",
        pan_encrypted=encrypt_pan(plain_pan),
        pan_hash=pan_hash(plain_pan),
    )
    db_session.add(investor)
    await db_session.commit()

    # Folio
    folio = Folio(
        investor_id=investor.id,
        number="1234567/89",
        amc_code="HDFC",
    )
    db_session.add(folio)
    await db_session.commit()

    # Transaction
    tx = Transaction(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec.id,
        date=date(2026, 2, 10),
        transaction_type="BUY",
        units=Decimal("100.50000000"),
        nav_or_price=Decimal("50.000000"),
        amount=Decimal("5025.00"),
        stamp_duty=Decimal("0.25"),
    )
    db_session.add(tx)

    # Holding
    holding = Holding(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec.id,
        as_of_date=date(2026, 2, 10),
        units=Decimal("100.50000000"),
        value_observed=Decimal("5500.00"),
    )
    db_session.add(holding)

    # InvestorValue
    val = InvestorValue(
        investor_id=investor.id,
        date=date(2026, 2, 10),
        invested_inr=Decimal("5025.00"),
        value_inr=Decimal("5500.00"),
    )
    db_session.add(val)

    # AppliedCorporateAction
    app_ca = AppliedCorporateAction(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec.id,
        kind="SPLIT",
        ex_date=date(2026, 2, 12),
        unit_multiplier=Decimal("2.000000"),
    )
    db_session.add(app_ca)

    # SecurityIntegrityStatus
    integrity = SecurityIntegrityStatus(
        investor_id=investor.id,
        folio_id=folio.id,
        security_id=sec.id,
        status="OK",
        tax_safe=True,
        units_from_transactions=Decimal("100.50000000"),
        units_from_holdings=Decimal("100.50000000"),
    )
    db_session.add(integrity)
    await db_session.commit()

    # Verify query by pan_hash and decrypted/masked properties
    stmt = select(Investor).where(Investor.pan_hash == pan_hash(plain_pan))
    res = await db_session.execute(stmt)
    found_investor = res.scalar_one()
    assert found_investor.name == "Raj Sharma"
    assert found_investor.pan_masked == "XXXXXX234F"
    assert found_investor.pan_plain == plain_pan

    # Test Cascade Delete: deleting investor should cascade-delete folio, transactions, values, and integrity
    await db_session.delete(found_investor)
    await db_session.commit()

    assert await db_session.get(Folio, folio.id) is None
    assert await db_session.get(Transaction, tx.id) is None
    assert await db_session.get(InvestorValue, val.id) is None


@pytest.mark.asyncio
async def test_import_auditing_and_quarantines(db_session) -> None:
    investor = Investor(
        user_id="user_999",
        name="Anita Patel",
        pan_encrypted=encrypt_pan("PQRST5678Z"),
        pan_hash=pan_hash("PQRST5678Z"),
    )
    db_session.add(investor)
    await db_session.commit()

    job = ImportJob(
        investor_id=investor.id,
        kind="cas_pdf",
        status="partially_reconciled",
        filename="cams_cas.pdf",
        result_json={"total_txs": 50, "quarantined": 1},
    )
    db_session.add(job)
    await db_session.commit()

    quarantine = ImportQuarantine(
        import_job_id=job.id,
        investor_id=investor.id,
        kind="UNRESOLVED_ISIN",
        security_name="Unknown New Offshore Equity Fund",
        isin="",
        folio_number="998877",
        reason="No ISIN could be matched in reference catalog",
        raw_json={"units": 500, "nav": 12.5},
        resolved=False,
    )
    db_session.add(quarantine)
    await db_session.commit()

    # Query back with selectinload
    stmt = (
        select(ImportJob)
        .where(ImportJob.id == job.id)
        .options(selectinload(ImportJob.quarantines))
    )
    res = await db_session.execute(stmt)
    q_job = res.scalar_one()
    assert q_job is not None
    assert len(q_job.quarantines) == 1
    assert q_job.quarantines[0].kind == "UNRESOLVED_ISIN"
    assert q_job.quarantines[0].resolved is False


@pytest.mark.asyncio
async def test_nav_history_unique_constraint(db_session) -> None:
    amc = AMC(code="NIPPON", name="Nippon India MF")
    db_session.add(amc)
    await db_session.commit()

    sec = Security(
        isin="INF204K01914",
        name="Nippon India Small Cap Fund",
        security_type="MF",
        amc_id=amc.id,
    )
    db_session.add(sec)
    await db_session.commit()

    # First NAV entry
    nav1 = NAVHistory(
        security_id=sec.id,
        date=date(2026, 3, 1),
        nav=Decimal("150.000000"),
    )
    db_session.add(nav1)
    await db_session.commit()

    # Duplicate NAV entry on same security and date must violate unique constraint
    nav2 = NAVHistory(
        security_id=sec.id,
        date=date(2026, 3, 1),
        nav=Decimal("151.000000"),
    )
    db_session.add(nav2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
