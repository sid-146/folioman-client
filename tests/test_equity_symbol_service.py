"""Unit tests for EquitySymbolService: symbol resolution from reference master and price backfill."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import ISINReference, Security
from folioman_client.services.equity_symbol_service import EquitySymbolService


@pytest.fixture
async def symbol_service():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = EquitySymbolService(engine=engine)
    yield service
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_symbols_from_isin_reference(symbol_service: EquitySymbolService):
    async with symbol_service.session_factory() as session:
        # Seed reference database
        ref1 = ISINReference(
            isin="INE002A01018",
            symbol="RELIANCE",
            name="Reliance Industries Ltd",
            exchange="NSE",
            type="EQUITY",
        )
        ref2 = ISINReference(
            isin="INE040A01034",
            symbol="HDFCBANK",
            name="HDFC Bank Ltd",
            exchange="BSE",
            type="EQUITY",
        )
        session.add_all([ref1, ref2])

        # Add held securities without symbol
        sec1 = Security(
            name="Reliance Industries",
            isin="INE002A01018",
            symbol="",
            security_type="EQUITY",
        )
        sec2 = Security(
            name="HDFC Bank",
            isin="INE040A01034",
            symbol="",
            security_type="EQUITY",
        )
        sec3 = Security(
            name="Unknown Stock",
            isin="INE999X01099",
            symbol="",
            security_type="EQUITY",
        )
        session.add_all([sec1, sec2, sec3])
        await session.commit()
        sec1_id, sec2_id = sec1.id, sec2.id

    # 1. Dry run
    dry_summary = await symbol_service.resolve_symbols(dry_run=True)
    assert dry_summary["unresolved_count"] == 3
    assert dry_summary["matched_count"] == 2
    assert dry_summary["updated_count"] == 0
    assert dry_summary["unmatched_count"] == 1
    assert dry_summary["unmatched"][0]["isin"] == "INE999X01099"

    # Verify no mutation occurred in dry run
    async with symbol_service.session_factory() as session:
        check_sec = await session.get(Security, sec1_id)
        assert check_sec.symbol == ""

    # 2. Live run with backfill
    with patch(
        "folioman_client.services.nav_service.NAVService.backfill_navs",
        new_callable=AsyncMock,
        return_value={"securities": 2, "points": 50},
    ) as mock_backfill:
        live_summary = await symbol_service.resolve_symbols(
            dry_run=False, backfill=True
        )
        assert live_summary["matched_count"] == 2
        assert live_summary["updated_count"] == 2
        assert live_summary["backfill"] == {"securities": 2, "points": 50}
        mock_backfill.assert_called_once()

    # Verify persistence
    async with symbol_service.session_factory() as session:
        sec1_updated = await session.get(Security, sec1_id)
        assert sec1_updated.symbol == "RELIANCE"
        assert sec1_updated.exchange == "NSE"

        sec2_updated = await session.get(Security, sec2_id)
        assert sec2_updated.symbol == "HDFCBANK"
        assert sec2_updated.exchange == "BSE"
