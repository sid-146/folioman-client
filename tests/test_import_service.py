"""Tests for CASImportService: statement persistence, deduplication, partial chaining, and quarantines."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import event, select

from folioman_client.core.cas_reader import ParsedCas
from folioman_client.core.models.cas import (
    CasInvestorIdentity,
    Depository,
    EcasAccountBlock,
    EcasHoldingLine,
    EcasStatement,
    MfCasLineItem,
    MfCasSchemeBlock,
    MfCasStatement,
)
from folioman_client.core.models.investor import Folio as CoreFolio
from folioman_client.core.models.security import Security as CoreSecurity
from folioman_client.core.models.security import SecurityType
from folioman_client.core.models.transaction import TransactionType
from folioman_client.core.parser import CASParseError, CASPasswordError
from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    Holding,
    ImportQuarantine,
    Investor,
    PartialBlock,
    Transaction,
)
from folioman_client.errors import FoliomanParseError, FoliomanPasswordError
from folioman_client.security.pan import pan_hash
from folioman_client.services.import_service import CASImportService


@pytest.fixture
async def import_service():
    """Provides a CASImportService backed by an isolated in-memory SQLite database."""
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = CASImportService(engine=engine)
    yield service
    await engine.dispose()


def _build_mf_statement() -> MfCasStatement:
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="PPFAS Flexi Cap Fund - Direct Plan - Growth",
        isin="INF879O01019",
        amfi_code="119551",
        metadata={"amc": "PPFAS Mutual Fund"},
    )
    fol = CoreFolio(folio_type="mf", number="12345/0", amc_code="PPFAS")
    block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal(0),
        closing_units=Decimal(100),
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 15),
                transaction_type=TransactionType.BUY,
                units=Decimal("100.0000"),
                nav=Decimal("50.0000"),
                amount=Decimal("5000.00"),
                stamp_duty=Decimal("0.25"),
                description="Purchase - SIP",
            )
        ],
    )
    return MfCasStatement(
        investor_name="Rahul Sharma",
        investor_email="rahul@example.com",
        pan_masked="XXXXXX1234F",
        statement_from=date(2026, 1, 1),
        statement_to=date(2026, 1, 31),
        schemes=[block],
    )


@pytest.mark.asyncio
async def test_import_complete_mf_statement(import_service: CASImportService) -> None:
    stmt = _build_mf_statement()
    identity = CasInvestorIdentity(
        name="Rahul Sharma", email="rahul@example.com", pan="ABCDE1234F"
    )
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    with patch(
        "folioman_client.services.import_service.read_cas", return_value=mock_parsed
    ):
        res = await import_service.import_cas(b"%PDF-1.4 dummy", "password123")

    assert res["status"] == "completed"
    assert res["schemes"] == 1
    assert res["transactions_created"] == 1
    assert res["transactions_skipped"] == 0
    assert res["partial_transactions"] == 0
    assert len(res["quarantined"]) == 0

    # Verify database persistence
    async with import_service.session_factory() as session:
        investor = (await session.execute(select(Investor))).scalar_one()
        assert investor.name == "Rahul Sharma"
        assert investor.pan_masked == "XXXXXX234F"
        assert investor.pan_hash == pan_hash("ABCDE1234F")

        txn = (await session.execute(select(Transaction))).scalar_one()
        assert txn.units == Decimal("100.0000")
        assert txn.cost_basis_complete is True
        assert txn.transaction_type == "BUY"


@pytest.mark.asyncio
async def test_import_idempotent_deduplication(
    import_service: CASImportService,
) -> None:
    stmt = _build_mf_statement()
    identity = CasInvestorIdentity(
        name="Rahul Sharma", email="rahul@example.com", pan="ABCDE1234F"
    )
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    with patch(
        "folioman_client.services.import_service.read_cas", return_value=mock_parsed
    ):
        # First import
        res1 = await import_service.import_cas(b"%PDF-1.4 dummy", "password123")
        assert res1["transactions_created"] == 1
        assert res1["transactions_skipped"] == 0

        # Second import of identical statement: should skip existing transaction
        res2 = await import_service.import_cas(b"%PDF-1.4 dummy", "password123")
        assert res2["transactions_created"] == 0
        assert res2["transactions_skipped"] == 1

    # Database still contains exactly one transaction
    async with import_service.session_factory() as session:
        txns = (await session.execute(select(Transaction))).scalars().all()
        assert len(txns) == 1


@pytest.mark.asyncio
async def test_import_mixed_new_and_duplicate_transactions(
    import_service: CASImportService,
) -> None:
    """Verify that importing an overlapping statement correctly distinguishes duplicates from new transactions."""
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="PPFAS Flexi Cap Fund - Direct Plan - Growth",
        isin="INF879O01019",
        amfi_code="119551",
    )
    fol = CoreFolio(folio_type="mf", number="12345/0", amc_code="PPFAS")
    identity = CasInvestorIdentity(
        name="Rahul Sharma", email="rahul@example.com", pan="ABCDE1234F"
    )

    def _make_line(i: int, day: int) -> MfCasLineItem:
        return MfCasLineItem(
            date=date(2026, 1, day),
            transaction_type=TransactionType.BUY,
            units=Decimal("10.0000"),
            nav=Decimal("100.0000"),
            amount=Decimal("1000.00"),
            balance=Decimal(str(10 * i)),
            description=f"SIP #{i}",
        )

    # Initial statement has transactions 1 through 5
    txns_first = [_make_line(i, day=i) for i in range(1, 6)]
    block1 = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal(0),
        closing_units=Decimal("50.0000"),
        transactions=txns_first,
    )
    stmt1 = MfCasStatement(
        statement_from=date(2026, 1, 1),
        statement_to=date(2026, 1, 5),
        schemes=[block1],
    )

    with patch(
        "folioman_client.services.import_service.read_cas",
        return_value=ParsedCas(mf=stmt1, investor=identity),
    ):
        res1 = await import_service.import_cas(b"%PDF-1.4 dummy", "password123")
        assert res1["transactions_created"] == 5
        assert res1["transactions_skipped"] == 0

    # Overlapping statement has transactions 3 through 8 (3 duplicates, 3 new)
    txns_second = [_make_line(i, day=i) for i in range(3, 9)]
    block2 = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal("20.0000"),
        closing_units=Decimal("80.0000"),
        transactions=txns_second,
    )
    stmt2 = MfCasStatement(
        statement_from=date(2026, 1, 3),
        statement_to=date(2026, 1, 8),
        schemes=[block2],
    )

    with patch(
        "folioman_client.services.import_service.read_cas",
        return_value=ParsedCas(mf=stmt2, investor=identity),
    ):
        res2 = await import_service.import_cas(b"%PDF-1.4 dummy", "password123")
        assert res2["transactions_created"] == 3
        assert res2["transactions_skipped"] == 3

    # Total in DB should be exactly 8 unique transactions (1 through 8)
    async with import_service.session_factory() as session:
        all_txns = (await session.execute(select(Transaction))).scalars().all()
        assert len(all_txns) == 8


@pytest.mark.asyncio
async def test_import_batch_dedup_large_statement_query_efficiency(
    import_service: CASImportService,
) -> None:
    """Verify that a large statement loads dedup keys in batches rather than querying row-by-row,

    demonstrating fewer database round trips (e.g. 3 chunk queries vs 1,200 individual queries).
    """
    total_txns = 1200
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="Large Scale Equity Fund",
        isin="INF999K01001",
        amfi_code="199001",
    )
    fol = CoreFolio(folio_type="mf", number="BATCH/100", amc_code="LARGE")
    identity = CasInvestorIdentity(
        name="Suresh Kumar", email="suresh@example.com", pan="ABCDE5678G"
    )

    txns = [
        MfCasLineItem(
            date=date(2025, 1, 1),
            transaction_type=TransactionType.BUY,
            units=Decimal("10.0000"),
            nav=Decimal("50.0000"),
            amount=Decimal("500.00"),
            balance=Decimal(str(10 * (i + 1))),
            description=f"Transaction #{i}",
        )
        for i in range(total_txns)
    ]
    block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal(0),
        closing_units=Decimal(str(10 * total_txns)),
        transactions=txns,
    )
    stmt = MfCasStatement(
        statement_from=date(2025, 1, 1),
        statement_to=date(2025, 12, 31),
        schemes=[block],
    )
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    # Intercept queries using SQLAlchemy's event hook on the underlying engine
    captured_queries: list[str] = []

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        captured_queries.append(statement)

    event.listen(
        import_service.engine.sync_engine,
        "before_cursor_execute",
        before_cursor_execute,
    )

    try:
        with patch(
            "folioman_client.services.import_service.read_cas",
            return_value=mock_parsed,
        ):
            res = await import_service.import_cas(b"%PDF-1.4 dummy", "secret")
    finally:
        event.remove(
            import_service.engine.sync_engine,
            "before_cursor_execute",
            before_cursor_execute,
        )

    assert res["status"] == "completed"
    assert res["transactions_created"] == total_txns

    # Identify batch dedup check queries (SELECT transactions.dedup_key ... IN (...))
    dedup_queries = [
        q
        for q in captured_queries
        if "transactions.dedup_key" in q and "IN" in q and "SELECT" in q
    ]

    # With chunk_size=500, 1,200 items should take ceil(1200 / 500) = 3 batch queries.
    # Under the old N+1 implementation, this would have taken 1,200 individual queries.
    assert len(dedup_queries) == 3
    assert len(dedup_queries) < total_txns


@pytest.mark.asyncio
async def test_import_partial_statement_with_opening_gap(
    import_service: CASImportService,
) -> None:
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="HDFC Flexi Cap",
        isin="INF179K01XQ0",
        amfi_code="118989",
    )
    fol = CoreFolio(folio_type="mf", number="999/11", amc_code="HDFC")
    # Opening balance 50, but prior ledger is empty -> partial period statement
    block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal("50.0000"),
        closing_units=Decimal("70.0000"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 6, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("20.0000"),
                nav=Decimal("80.0000"),
                amount=Decimal("1600.00"),
            )
        ],
    )
    stmt = MfCasStatement(
        investor_name="Pooja Patel",
        statement_from=date(2026, 6, 1),
        statement_to=date(2026, 6, 30),
        schemes=[block],
    )
    identity = CasInvestorIdentity(name="Pooja Patel", pan="PQRST5678Z")
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    with patch(
        "folioman_client.services.import_service.read_cas", return_value=mock_parsed
    ):
        res = await import_service.import_cas(b"%PDF-1.4 dummy", "secret")

    assert res["status"] == "partially_reconciled"
    assert res["partial_transactions"] == 1
    assert res["transactions_created"] == 0
    assert res["holdings_snapshotted"] == 1
    assert len(res["incomplete_history"]) == 1
    assert res["incomplete_history"][0]["reason"] == "opening_nonzero"

    # Verify database state
    async with import_service.session_factory() as session:
        # Transaction is flagged cost_basis_complete=False
        txn = (await session.execute(select(Transaction))).scalar_one()
        assert txn.cost_basis_complete is False

        # PartialBlock record created
        pb = (await session.execute(select(PartialBlock))).scalar_one()
        assert pb.opening_units == Decimal("50.0000")
        assert pb.closing_units == Decimal("70.0000")

        # Holding snapshot created
        h = (await session.execute(select(Holding))).scalar_one()
        assert h.units == Decimal("70.0000")
        assert h.source == "cas_pdf"


@pytest.mark.asyncio
async def test_upgrade_chained_partials(import_service: CASImportService) -> None:
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="HDFC Flexi Cap",
        isin="INF179K01XQ0",
        amfi_code="118989",
    )
    fol = CoreFolio(folio_type="mf", number="999/11", amc_code="HDFC")
    identity = CasInvestorIdentity(name="Pooja Patel", pan="PQRST5678Z")

    # 1. First import: Second Half of Year (partial: opening 50, buy 20, close 70)
    later_block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal("50.0000"),
        closing_units=Decimal("70.0000"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 7, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("20.0000"),
                nav=Decimal("80.0000"),
                amount=Decimal("1600.00"),
            )
        ],
    )
    later_stmt = MfCasStatement(
        statement_from=date(2026, 7, 1),
        statement_to=date(2026, 12, 31),
        schemes=[later_block],
    )
    with patch(
        "folioman_client.services.import_service.read_cas",
        return_value=ParsedCas(mf=later_stmt, investor=identity),
    ):
        await import_service.import_cas(b"%PDF-1.4 dummy", "secret")

    # Verify it is partial
    async with import_service.session_factory() as session:
        assert len((await session.execute(select(PartialBlock))).scalars().all()) == 1
        txn = (await session.execute(select(Transaction))).scalar_one()
        assert txn.cost_basis_complete is False

    # 2. Second import: First Half of Year (complete: opening 0, buy 50, close 50)
    earlier_block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal(0),
        closing_units=Decimal("50.0000"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("50.0000"),
                nav=Decimal("70.0000"),
                amount=Decimal("3500.00"),
            )
        ],
    )
    earlier_stmt = MfCasStatement(
        statement_from=date(2026, 1, 1),
        statement_to=date(2026, 6, 30),
        schemes=[earlier_block],
    )
    with patch(
        "folioman_client.services.import_service.read_cas",
        return_value=ParsedCas(mf=earlier_stmt, investor=identity),
    ):
        res = await import_service.import_cas(b"%PDF-1.4 dummy2", "secret")

    # 3. Chained partial block should have been upgraded!
    async with import_service.session_factory() as session:
        # Partial blocks should now be empty (upgraded)
        pbs = (await session.execute(select(PartialBlock))).scalars().all()
        assert len(pbs) == 0

        # Both transactions must now be cost_basis_complete=True
        txns = (await session.execute(select(Transaction))).scalars().all()
        assert len(txns) == 2
        for t in txns:
            assert t.cost_basis_complete is True

        # Redundant CAS holding snapshot should be cleaned up
        holdings = (
            (await session.execute(select(Holding).where(Holding.source == "cas_pdf")))
            .scalars()
            .all()
        )
        assert len(holdings) == 0


@pytest.mark.asyncio
async def test_import_quarantine_on_block_error(
    import_service: CASImportService,
) -> None:
    # Malformed block: units is not a valid number
    bad_sec = CoreSecurity(
        type=SecurityType.MF, name="Corrupted Fund", isin="INF000000000"
    )
    bad_fol = CoreFolio(folio_type="mf", number="ERR-1")
    bad_block = MfCasSchemeBlock(security=bad_sec, folio=bad_fol)

    good_stmt = _build_mf_statement()
    good_stmt.schemes.append(bad_block)

    identity = CasInvestorIdentity(name="Rahul Sharma", pan="ABCDE1234F")

    real_upsert = import_service._upsert_security

    async def fake_upsert(session, core_sec, amc_id=None):
        if core_sec.name == "Corrupted Fund":
            raise ValueError("Corrupted record")
        return await real_upsert(session, core_sec, amc_id)

    # Force an exception only when upserting bad_sec
    with (
        patch.object(import_service, "_upsert_security", side_effect=fake_upsert),
        patch(
            "folioman_client.services.import_service.read_cas",
            return_value=ParsedCas(mf=good_stmt, investor=identity),
        ),
    ):
        res = await import_service.import_cas(b"%PDF-1.4 dummy", "secret")

    # Should quarantine the bad block without failing the whole statement
    assert res["status"] == "partially_reconciled"
    assert len(res["quarantined"]) == 1
    assert res["quarantined"][0]["security"] == "Corrupted Fund"

    async with import_service.session_factory() as session:
        q_rows = (await session.execute(select(ImportQuarantine))).scalars().all()
        assert len(q_rows) == 1
        assert q_rows[0].security_name == "Corrupted Fund"
        assert q_rows[0].resolved is False


@pytest.mark.asyncio
async def test_import_ecas_statement(import_service: CASImportService) -> None:
    sec = CoreSecurity(
        type=SecurityType.EQUITY,
        name="Reliance Industries Ltd",
        isin="INE002A01018",
        symbol="RELIANCE",
    )
    fol = CoreFolio(folio_type="demat", number="1208160012345678", broker="Zerodha")
    line = EcasHoldingLine(
        security=sec,
        units=Decimal(25),
        value_observed=Decimal("75000.00"),
        avg_cost_observed=Decimal("2500.00"),
    )
    acc = EcasAccountBlock(folio=fol, kind="demat", holdings=[line])
    stmt = EcasStatement(
        depository=Depository.CDSL,
        statement_date=date(2026, 2, 28),
        investor_name="Anita Roy",
        pan_masked="XXXXXX9876Z",
        accounts=[acc],
    )
    identity = CasInvestorIdentity(name="Anita Roy", pan="XYZPK9876Z")
    mock_parsed = ParsedCas(ecas=stmt, investor=identity)

    with patch(
        "folioman_client.services.import_service.read_cas", return_value=mock_parsed
    ):
        res = await import_service.import_cas(b"%PDF-1.4 dummy", "secret")

    assert res["status"] == "completed"
    assert res["is_ecas"] is True
    assert res["holdings_snapshotted"] == 1

    async with import_service.session_factory() as session:
        holding = (await session.execute(select(Holding))).scalar_one()
        assert holding.units == Decimal(25)
        assert holding.value_observed == Decimal("75000.00")
        assert holding.source == "ecas"


@pytest.mark.asyncio
async def test_import_password_error_wrapping(import_service: CASImportService) -> None:
    with (
        patch(
            "folioman_client.services.import_service.read_cas",
            side_effect=CASPasswordError("Bad password"),
        ),
        pytest.raises(FoliomanPasswordError),
    ):
        await import_service.import_cas(b"%PDF-1.4 dummy", "wrong")


@pytest.mark.asyncio
async def test_import_parse_error_wrapping(import_service: CASImportService) -> None:
    with (
        patch(
            "folioman_client.services.import_service.read_cas",
            side_effect=CASParseError("Corrupted stream"),
        ),
        pytest.raises(FoliomanParseError),
    ):
        await import_service.import_cas(b"%PDF-1.4 dummy", "secret")
