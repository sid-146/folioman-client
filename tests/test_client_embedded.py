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
    identity = CasInvestorIdentity(
        name="Priya Patel", email="priya@example.com", pan="ABCDE9876P"
    )
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    async with FoliomanClient(
        database_url="sqlite+aiosqlite:///:memory:",
        user_id="advisor_1",
    ) as client:
        with patch(
            "folioman_client.services.import_service.read_cas", return_value=mock_parsed
        ):
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


@pytest.mark.asyncio
async def test_client_embedded_investors_and_folios():
    async with FoliomanClient(database_url="sqlite+aiosqlite:///:memory:") as client:
        inv = await client.investors.create(
            name="Rohit Sharma",
            pan="ABCDE5555R",
            email="rohit@example.com",
        )
        assert inv.id > 0
        assert inv.name == "Rohit Sharma"
        assert inv.pan_masked == "XXXXXX555R"

        inv_list = await client.investors.list()
        assert len(inv_list) == 1
        assert inv_list[0].id == inv.id

        inv_get = await client.investors.get(inv.id)
        assert inv_get.name == "Rohit Sharma"
        assert inv_get.pan_masked == "XXXXXX555R"

        fol1 = await client.folios.create(inv.id, "FOL-101", amc_code="NIPPON")
        fol2 = await client.folios.create(inv.id, "FOL-102", amc_code="NIPPON")
        assert fol1["number"] == "FOL-101"
        assert fol2["number"] == "FOL-102"

        folios = await client.folios.list(inv.id)
        assert len(folios) == 2

        # Delete a folio
        assert await client.folios.delete(inv.id, fol1["id"]) is True
        folios_after = await client.folios.list(inv.id)
        assert len(folios_after) == 1
        assert folios_after[0].id == fol2["id"]

        # Deleting non-existent folio returns False
        assert await client.folios.delete(inv.id, 99999) is False


@pytest.mark.asyncio
async def test_client_embedded_reconcile_symbols_and_ca_delegation():
    async with FoliomanClient(database_url="sqlite+aiosqlite:///:memory:") as client:
        with (
            patch.object(
                client._reconcile_service,
                "reconcile_all",
                new_callable=AsyncMock,
                return_value={"investors_count": 1, "statuses_count": 2},
            ) as mock_rec_all,
            patch.object(
                client._symbol_service,
                "resolve_symbols",
                new_callable=AsyncMock,
                return_value={"matched_count": 3, "updated_count": 3},
            ) as mock_sym,
            patch.object(
                client._ca_service,
                "refresh_corporate_actions",
                new_callable=AsyncMock,
                return_value={"actions_fetched": 4},
            ) as mock_ca_refresh,
        ):
            rec_res = await client.reconcile.all()
            assert rec_res["investors_count"] == 1
            mock_rec_all.assert_called_once()

            sym_res = await client.symbols.resolve(dry_run=True)
            assert sym_res["matched_count"] == 3
            mock_sym.assert_called_once_with(
                dry_run=True, backfill=False, force_backfill=False
            )

            ca_res = await client.corporate_actions.refresh(since_year=2020)
            assert ca_res["actions_fetched"] == 4
            mock_ca_refresh.assert_called_once_with(security_ids=None, since_year=2020)


@pytest.mark.asyncio
async def test_client_embedded_phase6_delegation():
    async with FoliomanClient(database_url="sqlite+aiosqlite:///:memory:") as client:
        with (
            patch.object(
                client._valuation_service,
                "build_investor_summary",
                new_callable=AsyncMock,
                return_value={
                    "investor_id": 1,
                    "as_of": date(2024, 6, 1),
                    "total_inr": Decimal("50000"),
                    "holdings_count": 1,
                    "asset_mix": [],
                    "top_holdings": [],
                    "period_returns": [],
                },
            ) as mock_port,
            patch.object(
                client._valuation_service,
                "value_series",
                new_callable=AsyncMock,
                return_value={
                    "investor_id": 1,
                    "start": date(2023, 1, 1),
                    "end": date(2024, 1, 1),
                    "granularity": "monthly",
                    "points": [],
                },
            ) as mock_val_series,
            patch.object(
                client._valuation_service,
                "get_valuation_status",
                new_callable=AsyncMock,
                return_value={
                    "investor_id": 1,
                    "status": "ready",
                    "is_provisional": False,
                },
            ) as mock_val_status,
            patch.object(
                client._capital_gains_service,
                "list_capital_gains_by_fy",
                new_callable=AsyncMock,
                return_value=[
                    {"fy": "2024-25", "stcg": Decimal("0"), "ltcg": Decimal("1000")}
                ],
            ) as mock_cg_list,
            patch.object(
                client._capital_gains_service,
                "get_capital_gains_report",
                new_callable=AsyncMock,
                return_value={
                    "fy": "2024-25",
                    "stcg_total": Decimal("0"),
                    "ltcg_total": Decimal("1000"),
                    "exempt_total": Decimal("0"),
                    "rows": [],
                },
            ) as mock_cg_get,
            patch.object(
                client._capital_gains_service,
                "get_schedule_112a",
                new_callable=AsyncMock,
                return_value={
                    "fy": "2024-25",
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                },
            ) as mock_s112a,
        ):
            p = await client.portfolio.get(investor_id=1)
            assert p.total_inr == Decimal("50000")
            mock_port.assert_called_once_with(1, as_of=None)

            vs = await client.valuations.list(investor_id=1, granularity="monthly")
            assert vs.points == []
            mock_val_series.assert_called_once_with(
                1, from_date=None, to_date=None, granularity="monthly"
            )

            vst = await client.valuations.status(investor_id=1)
            assert vst.status == "ready"
            mock_val_status.assert_called_once_with(1)

            cgl = await client.capital_gains.list(investor_id=1)
            assert len(cgl) == 1
            assert cgl[0].fy == "2024-25"
            mock_cg_list.assert_called_once_with(1, include_unreconciled=False)

            cgr = await client.capital_gains.get(investor_id=1, fy="2024-25")
            assert cgr.fy == "2024-25"
            assert cgr.ltcg_total == Decimal("1000")
            mock_cg_get.assert_called_once_with(
                1, fy="2024-25", include_unreconciled=False
            )

            s = await client.capital_gains.schedule_112a(investor_id=1, fy="2024-25")
            assert s["fy"] == "2024-25"
            mock_s112a.assert_called_once_with(
                1, fy="2024-25", include_unreconciled=False
            )
