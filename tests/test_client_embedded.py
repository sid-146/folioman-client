"""Tests for FoliomanClient embedded mode (imports, navs, isin, scheduler)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from folioman_client.client import FoliomanClient
from folioman_client.core.cas_reader import ParsedCas
from folioman_client.core.models.cas import (
    CasInvestorIdentity,
    MfCasLineItem,
    MfCasSchemeBlock,
    MfCasStatement,
)
from folioman_client.core.models.investor import Folio as CoreFolio
from folioman_client.core.models.security import Security as CoreSecurity, SecurityType
from folioman_client.core.models.transaction import TransactionType


def _sample_mf_statement() -> MfCasStatement:
    sec = CoreSecurity(
        type=SecurityType.MF,
        name="Axis Bluechip Fund - Direct Plan - Growth",
        isin="INF128I01AS5",
        amfi_code="120503",
        metadata={"amc": "Axis Mutual Fund"},
    )
    fol = CoreFolio(folio_type="mf", number="9101112/0", amc_code="AXIS")
    block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal("0"),
        closing_units=Decimal("50"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 2, 10),
                transaction_type=TransactionType.BUY,
                units=Decimal("50.0000"),
                nav=Decimal("40.0000"),
                amount=Decimal("2000.00"),
                stamp_duty=Decimal("0.10"),
                description="Purchase",
            )
        ],
    )
    return MfCasStatement(
        investor_name="Priya Patel",
        investor_email="priya@example.com",
        pan_masked="XXXXXX9876P",
        statement_from=date(2026, 2, 1),
        statement_to=date(2026, 2, 28),
        schemes=[block],
    )


@pytest.mark.asyncio
async def test_client_embedded_imports_delegation():
    stmt = _sample_mf_statement()
    identity = CasInvestorIdentity(name="Priya Patel", email="priya@example.com", pan="ABCDE9876P")
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    async with FoliomanClient(
        database_url="sqlite+aiosqlite:///:memory:",
        user_id="advisor_1",
    ) as client:
        with patch("folioman_client.services.import_service.read_cas", return_value=mock_parsed):
            result = await client.imports.cas_pdf(b"%PDF-1.4 dummy", "mypassword")

        assert result["status"] == "completed"
        assert result["schemes"] == 1
        assert result["transactions_created"] == 1
        assert result["investor_name"] == "Priya Patel"
        assert result["pan_masked"] == "XXXXXX876P"


@pytest.mark.asyncio
async def test_client_embedded_navs_delegation():
    async with FoliomanClient(database_url="sqlite+aiosqlite:///:memory:") as client:
        with (
            patch.object(
                client._nav_service,
                "refresh_navs",
                new_callable=AsyncMock,
                return_value={"updated": 5, "skipped": 0, "errors": 0},
            ) as mock_refresh,
            patch.object(
                client._nav_service,
                "backfill_navs",
                new_callable=AsyncMock,
                return_value={"securities": 2, "points": 100},
            ) as mock_backfill,
            patch.object(
                client._nav_service,
                "get_nav_freshness",
                new_callable=AsyncMock,
                return_value=[{"security_id": 1, "status": "fresh"}],
            ) as mock_freshness,
        ):
            refresh_res = await client.navs.refresh(types=["mf"])
            assert refresh_res["updated"] == 5
            mock_refresh.assert_called_once_with(types=["mf"])

            backfill_res = await client.navs.backfill(force=True)
            assert backfill_res["points"] == 100
            mock_backfill.assert_called_once_with(force=True)

            freshness_res = await client.navs.freshness()
            assert len(freshness_res) == 1
            assert freshness_res[0]["status"] == "fresh"
            mock_freshness.assert_called_once()


@pytest.mark.asyncio
async def test_client_embedded_isin_delegation():
    async with FoliomanClient(database_url="sqlite+aiosqlite:///:memory:") as client:
        with (
            patch.object(
                client._isin_service,
                "get_reference_status",
                new_callable=AsyncMock,
                return_value={"is_seeded": True, "schemes_count": 15000},
            ) as mock_status,
            patch.object(
                client._isin_service,
                "seed_reference_data",
                new_callable=AsyncMock,
                return_value={"seeded": True, "schemes_count": 15000},
            ) as mock_seed,
            patch.object(
                client._isin_service,
                "update_reference_data",
                new_callable=AsyncMock,
                return_value={"updated": True, "version": "2026.04.11"},
            ) as mock_update,
        ):
            status = await client.isin.status()
            assert status["is_seeded"] is True
            mock_status.assert_called_once()

            seed_res = await client.isin.seed(force=False)
            assert seed_res["seeded"] is True
            mock_seed.assert_called_once_with(force=False, source_path=None)

            update_res = await client.isin.update()
            assert update_res["updated"] is True
            mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_client_embedded_scheduler_lifecycle():
    async with FoliomanClient(
        database_url="sqlite+aiosqlite:///:memory:",
        start_scheduler=True,
    ) as client:
        assert client._scheduler is not None
        assert client._scheduler.is_running is True

    # After exiting context manager, scheduler must be stopped
    assert client._scheduler.is_running is False
