"""Folioman API Client.

A thin, async, typed Python client for the Folioman REST API.
Handles HTTP transport, JWT token lifecycle (obtain, store, inject, refresh, retry on 401),
and response parsing into typed Pydantic models.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Literal

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.auth import JWTAuthManager
from folioman_client.config import FoliomanSettings, settings as default_settings
from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.models import SecurityIntegrityStatus
from folioman_client.errors import (
    FoliomanAPIError,
    FoliomanAuthError,
    FoliomanNotFoundError,
)
from folioman_client.models import (
    CapitalGainsFyPoint,
    CapitalGainsReport,
    Holding,
    Investor,
    InvestorDetail,
    PortfolioSummary,
    SchemeDetail,
    Transaction,
    ValuationStatus,
    ValueSeries,
)
from folioman_client.services.capital_gains_service import CapitalGainsService
from folioman_client.services.corporate_action_service import CorporateActionService
from folioman_client.services.equity_symbol_service import EquitySymbolService
from folioman_client.services.import_service import CASImportService
from folioman_client.services.isin_service import ISINService
from folioman_client.services.ledger_service import LedgerService
from folioman_client.services.nav_service import NAVService
from folioman_client.services.reconciliation_service import ReconciliationService
from folioman_client.services.scheduler import FoliomanScheduler
from folioman_client.services.valuation_service import ValuationService


class _BaseResource:
    """Base class for API resource sub-clients."""

    def __init__(self, client: FoliomanClient) -> None:
        self._client = client


class InvestorsResource(_BaseResource):
    """Endpoints for managing and querying investors."""

    async def list(
        self,
        *,
        family_id: int | None = None,
        unaffiliated: bool = False,
    ) -> list[Investor]:
        """List investors accessible to the authenticated advisor.

        Args:
            family_id: Filter by parent family group ID.
            unaffiliated: If True, only returns investors not affiliated with any family.

        Returns:
            A list of Investor summary models.
        """
        if self._client.is_remote:
            params: dict[str, Any] = {}
            if family_id is not None:
                params["family_id"] = family_id
            if unaffiliated:
                params["unaffiliated"] = "true"

            data = await self._client.request("GET", "/investors/", params=params)
            return [Investor.model_validate(item) for item in data]

        data = await self._client._ledger_service.list_investors(
            user_id=self._client.user_id,
            family_id=family_id,
            unaffiliated=unaffiliated,
        )
        return [Investor.model_validate(item) for item in data]

    async def get(self, investor_id: int) -> InvestorDetail:
        """Get investor details including masked PAN.

        Args:
            investor_id: Unique identifier of the investor.

        Returns:
            InvestorDetail model containing extended profile information.
        """
        if self._client.is_remote:
            data = await self._client.request("GET", f"/investors/{investor_id}")
            return InvestorDetail.model_validate(data)

        data = await self._client._ledger_service.get_investor(investor_id)
        return InvestorDetail.model_validate(data)

    async def create(
        self,
        name: str,
        *,
        pan: str | None = None,
        email: str = "",
        family_id: int | None = None,
        is_huf: bool = False,
        relation: str = "",
    ) -> InvestorDetail:
        """Create a new investor with encrypted PAN.

        Args:
            name: Full name.
            pan: PAN string.
            email: Email address.
            family_id: Optional parent family group ID.
            is_huf: Whether investor is HUF.
            relation: Relationship label.

        Returns:
            InvestorDetail model.
        """
        data = await self._client._ledger_service.create_investor(
            user_id=self._client.user_id,
            name=name,
            pan=pan,
            email=email,
            family_id=family_id,
            is_huf=is_huf,
            relation=relation,
        )
        return InvestorDetail.model_validate(data)


class PortfolioResource(_BaseResource):
    """Endpoints for investor portfolio summary and allocation."""

    async def get(
        self,
        investor_id: int,
        *,
        as_of: date | str | None = None,
    ) -> PortfolioSummary:
        """Get the full portfolio summary, metrics, and asset mix for an investor.

        Args:
            investor_id: The ID of the investor.
            as_of: Optional point-in-time valuation date (YYYY-MM-DD or date object).

        Returns:
            PortfolioSummary model containing metrics, holdings, and allocation mixes.

        Raises:
            FoliomanNotFoundError: If the investor ID does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        as_of_date = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        if not self._client.is_remote:
            data = await self._client._valuation_service.build_investor_summary(
                investor_id, as_of=as_of_date
            )
            return PortfolioSummary.model_validate(data)

        params: dict[str, Any] = {}
        if as_of is not None:
            params["as_of"] = (
                as_of.isoformat() if isinstance(as_of, date) else str(as_of)
            )

        data = await self._client.request(
            "GET", f"/investors/{investor_id}/summary", params=params
        )
        return PortfolioSummary.model_validate(data)


class HoldingsResource(_BaseResource):
    """Endpoints for querying investor holdings and scheme details."""

    async def list(
        self,
        investor_id: int,
        *,
        as_of: date | str | None = None,
    ) -> list[Holding]:
        """List priced holdings for an investor (extracted from portfolio summary).

        Args:
            investor_id: The ID of the investor.
            as_of: Optional point-in-time date.

        Returns:
            A list of Holding models.

        """
        summary = await self._client.portfolio.get(investor_id, as_of=as_of)
        return summary.holdings

    async def get(
        self,
        investor_id: int,
        security_id: int,
        *,
        as_of: date | str | None = None,
    ) -> SchemeDetail:
        """Get detailed holding/scheme information (NAV history, transactions, folios).

        Args:
            investor_id: The ID of the investor.
            security_id: The ID of the security/scheme.
            as_of: Optional point-in-time valuation date.

        Returns:
            SchemeDetail model with full NAV points, folio balances, and transactions.

        Raises:
            FoliomanNotFoundError: If the investor or security does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        as_of_date = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        if not self._client.is_remote:
            data = await self._client._valuation_service.build_scheme_detail(
                investor_id, security_id, as_of=as_of_date
            )
            return SchemeDetail.model_validate(data)

        params: dict[str, Any] = {}
        if as_of is not None:
            params["as_of"] = (
                as_of.isoformat() if isinstance(as_of, date) else str(as_of)
            )

        data = await self._client.request(
            "GET",
            f"/investors/{investor_id}/holdings/{security_id}",
            params=params,
        )
        return SchemeDetail.model_validate(data)


class TransactionsResource(_BaseResource):
    """Endpoints for querying and recording transaction ledger entries."""

    async def list(
        self,
        investor_id: int,
        *,
        security_id: int | None = None,
        folio_id: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Transaction]:
        """List all transactions for an investor.

        Args:
            investor_id: The ID of the investor.
            security_id: Optional security ID filter.
            folio_id: Optional folio ID filter.
            from_date: Optional start date filter.
            to_date: Optional end date filter.

        Returns:
            List of Transaction ledger entries.
        """
        if self._client.is_remote:
            data = await self._client.request(
                "GET", f"/investors/{investor_id}/transactions"
            )
            return [Transaction.model_validate(item) for item in data]

        data = await self._client._ledger_service.list_transactions(
            investor_id,
            security_id=security_id,
            folio_id=folio_id,
            from_date=from_date,
            to_date=to_date,
        )
        return [Transaction.model_validate(item) for item in data]

    async def create(
        self,
        *,
        investor_id: int,
        security_id: int,
        date: date,
        transaction_type: str,
        units: Decimal | str,
        nav_or_price: Decimal | str,
        amount: Decimal | str | None = None,
        folio_id: int | None = None,
        fees: Decimal | str = "0",
        stamp_duty: Decimal | str = "0",
        narration: str = "",
        source: str = "manual",
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Manually record a trade transaction into the ledger."""
        return await self._client._ledger_service.create_transaction(
            investor_id=investor_id,
            security_id=security_id,
            date=date,
            transaction_type=transaction_type,
            units=units,
            nav_or_price=nav_or_price,
            amount=amount,
            folio_id=folio_id,
            fees=fees,
            stamp_duty=stamp_duty,
            narration=narration,
            source=source,
            source_ref=source_ref,
        )

    async def create_opening_lot(
        self,
        *,
        investor_id: int,
        folio_id: int,
        security_id: int,
        units: Decimal | str,
        cost_basis: Decimal | str,
        as_of_date: date,
        classification: str = "ipo_allotment",
    ) -> dict[str, Any]:
        """Record an opening lot for a snapshot-only position."""
        return await self._client._ledger_service.create_opening_lot(
            investor_id=investor_id,
            folio_id=folio_id,
            security_id=security_id,
            units=units,
            cost_basis=cost_basis,
            as_of_date=as_of_date,
            classification=classification,
        )


class ValuationsResource(_BaseResource):
    """Endpoints for portfolio net-worth history and valuation status."""

    async def list(
        self,
        investor_id: int,
        *,
        from_date: date | str | None = None,
        to_date: date | str | None = None,
        granularity: Literal["daily", "weekly", "monthly"] = "monthly",
    ) -> ValueSeries:
        """Get net-worth time series reconstructed from ledger and NAV history.

        Args:
            investor_id: The ID of the investor.
            from_date: Start date of series.
            to_date: End date of series.
            granularity: Sampling frequency ('daily', 'weekly', or 'monthly').

        Returns:
            ValueSeries model containing historical valuation points.

        Raises:
            FoliomanNotFoundError: If the investor does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        from_d = (
            date.fromisoformat(from_date) if isinstance(from_date, str) else from_date
        )
        to_d = date.fromisoformat(to_date) if isinstance(to_date, str) else to_date
        if not self._client.is_remote:
            data = await self._client._valuation_service.value_series(
                investor_id, from_date=from_d, to_date=to_d, granularity=granularity
            )
            return ValueSeries.model_validate(data)

        params: dict[str, Any] = {"granularity": granularity}
        if from_date is not None:
            params["from"] = (
                from_date.isoformat() if isinstance(from_date, date) else str(from_date)
            )
        if to_date is not None:
            params["to"] = (
                to_date.isoformat() if isinstance(to_date, date) else str(to_date)
            )

        data = await self._client.request(
            "GET",
            f"/investors/{investor_id}/value-series",
            params=params,
        )
        return ValueSeries.model_validate(data)

    async def status(self, investor_id: int) -> ValuationStatus:
        """Get the current valuation calculation readiness status for an investor.

        Args:
            investor_id: The ID of the investor.

        Returns:
            ValuationStatus model indicating calculation state and coverage.

        Raises:
            FoliomanNotFoundError: If the investor does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        if not self._client.is_remote:
            data = await self._client._valuation_service.get_valuation_status(
                investor_id
            )
            return ValuationStatus.model_validate(data)

        data = await self._client.request(
            "GET", f"/investors/{investor_id}/valuation-status"
        )
        return ValuationStatus.model_validate(data)


class CapitalGainsResource(_BaseResource):
    """Endpoints for realised capital gains reporting."""

    async def list(
        self,
        investor_id: int,
        *,
        include_unreconciled: bool = False,
    ) -> list[CapitalGainsFyPoint]:
        """List realised STCG/LTCG across every financial year with disposals.

        Args:
            investor_id: The ID of the investor.
            include_unreconciled: Whether to include unreconciled transactions.

        Returns:
            List of CapitalGainsFyPoint models summarizing capital gains by financial year.

        Raises:
            FoliomanNotFoundError: If the investor does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        if not self._client.is_remote:
            data = await self._client._capital_gains_service.list_capital_gains_by_fy(
                investor_id, include_unreconciled=include_unreconciled
            )
            return [CapitalGainsFyPoint.model_validate(item) for item in data]

        params = {"include_unreconciled": str(include_unreconciled).lower()}
        data = await self._client.request(
            "GET",
            f"/investors/{investor_id}/reports/capital-gains-by-fy",
            params=params,
        )
        return [CapitalGainsFyPoint.model_validate(item) for item in data]

    async def get(
        self,
        investor_id: int,
        *,
        fy: str,
        include_unreconciled: bool = False,
    ) -> CapitalGainsReport:
        """Get realised capital gains report for a specific financial year.

        Args:
            investor_id: The ID of the investor.
            fy: Financial year string, e.g. "2024-25".
            include_unreconciled: Whether to include unreconciled transactions.

        Returns:
            CapitalGainsReport model with detailed lot-level gains.

        Raises:
            FoliomanNotFoundError: If the investor does not exist.
            FoliomanAuthError: If authentication fails.
            FoliomanAPIError: If the server returns an error response.
        """
        if not self._client.is_remote:
            data = await self._client._capital_gains_service.get_capital_gains_report(
                investor_id, fy=fy, include_unreconciled=include_unreconciled
            )
            return CapitalGainsReport.model_validate(data)

        params = {
            "fy": fy,
            "include_unreconciled": str(include_unreconciled).lower(),
        }
        data = await self._client.request(
            "GET",
            f"/investors/{investor_id}/exports/capital-gains",
            params=params,
        )
        return CapitalGainsReport.model_validate(data)

    async def schedule_112a(
        self,
        investor_id: int,
        *,
        fy: str,
        include_unreconciled: bool = False,
    ) -> dict[str, Any]:
        """Export official Schedule 112A rows and columns for Indian tax return filing."""
        if not self._client.is_remote:
            return await self._client._capital_gains_service.get_schedule_112a(
                investor_id, fy=fy, include_unreconciled=include_unreconciled
            )
        params = {
            "fy": fy,
            "include_unreconciled": str(include_unreconciled).lower(),
        }
        return await self._client.request(
            "GET",
            f"/investors/{investor_id}/exports/schedule-112a",
            params=params,
        )


class ImportsResource(_BaseResource):
    """Resource sub-client for importing CAS statement files."""

    def __init__(
        self, client: FoliomanClient, import_service: CASImportService
    ) -> None:
        super().__init__(client)
        self._service = import_service

    async def cas_pdf(
        self,
        file_path_or_bytes: str | Path | bytes | io.IOBase | BinaryIO,
        password: str,
        *,
        investor_id: int | None = None,
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Import a CAMS/KFintech MF CAS or NSDL/CDSL eCAS PDF into the active database.

        Args:
            file_path_or_bytes: File system path or raw PDF byte buffer.
            password: PDF unlock password.
            investor_id: Optional target investor ID.
            source_ref: Optional custom audit source reference.

        Returns:
            Dictionary summary of imported entities, transactions, and status.
        """
        return await self._service.import_cas(
            file_path_or_bytes,
            password,
            user_id=self._client.user_id,
            investor_id=investor_id,
            source_ref=source_ref,
        )


class NavsResource(_BaseResource):
    """Resource sub-client for managing NAV price feeds and backfilling."""

    def __init__(self, client: FoliomanClient, nav_service: NAVService) -> None:
        super().__init__(client)
        self._service = nav_service

    async def refresh(self, *, types: list[str] | None = None) -> dict[str, Any]:
        """Fetch latest available NAVs and market closing prices for held securities."""
        return await self._service.refresh_navs(types=types)

    async def backfill(self, *, force: bool = False) -> dict[str, Any]:
        """Backfill historical NAV price points for all held securities."""
        return await self._service.backfill_navs(force=force)

    async def freshness(self) -> list[dict[str, Any]]:
        """Return price freshness and staleness metrics for all active securities."""
        return await self._service.get_nav_freshness()


class ISINResource(_BaseResource):
    """Resource sub-client for managing ISIN and scheme master reference catalog."""

    def __init__(self, client: FoliomanClient, isin_service: ISINService) -> None:
        super().__init__(client)
        self._service = isin_service

    async def seed(
        self, *, force: bool = False, source_path: Path | None = None
    ) -> dict[str, Any]:
        """Ingest the reference master dataset into the active database."""
        return await self._service.seed_reference_data(
            force=force, source_path=source_path
        )

    async def update(self) -> dict[str, Any]:
        """Check for and ingest upstream reference updates."""
        return await self._service.update_reference_data()

    async def status(self) -> dict[str, Any]:
        """Get current status and row counts of the reference catalog."""
        return await self._service.get_reference_status()


class FoliosResource(_BaseResource):
    """Resource sub-client for investor folios and demat accounts."""

    def __init__(self, client: FoliomanClient, service: LedgerService) -> None:
        super().__init__(client)
        self._service = service

    async def list(self, investor_id: int) -> list[dict[str, Any]]:
        """List all accounts and folios belonging to an investor."""
        return await self._service.list_folios(investor_id)

    async def create(
        self,
        investor_id: int,
        number: str,
        *,
        amc_code: str = "",
        broker: str = "",
        folio_type: str = "mf",
    ) -> dict[str, Any]:
        """Create a new folio record."""
        return await self._service.create_folio(
            investor_id, number, amc_code=amc_code, broker=broker, folio_type=folio_type
        )

    async def merge(
        self,
        investor_id: int,
        source_folio_id: int,
        target_folio_id: int,
    ) -> dict[str, Any]:
        """Merge source folio into target folio."""
        return await self._service.merge_folios(
            investor_id, source_folio_id, target_folio_id
        )


class ReconcileResource(_BaseResource):
    """Resource sub-client for running ledger and holding reconciliations."""

    def __init__(self, client: FoliomanClient, service: ReconciliationService) -> None:
        super().__init__(client)
        self._service = service

    async def all(self, *, user_id: str | None = None) -> dict[str, Any]:
        """Reconcile all positions across all investors."""
        return await self._service.reconcile_all(
            user_id=user_id or self._client.user_id
        )

    async def investor(self, investor_id: int) -> dict[str, Any]:
        """Reconcile all security positions for a single investor."""
        return await self._service.reconcile_investor(investor_id)

    async def position(
        self, investor_id: int, security_id: int, folio_id: int
    ) -> SecurityIntegrityStatus | None:
        """Reconcile a single (investor, security, folio) position."""
        async with self._service.session_factory() as session:
            status = await self._service.reconcile_security_folio(
                session, investor_id, security_id, folio_id
            )
            await session.commit()
            return status

    async def acknowledge(
        self, investor_id: int, security_id: int, folio_id: int
    ) -> dict[str, Any]:
        """Acknowledge a unit mismatch on a position."""
        return await self._service.acknowledge_mismatch(
            investor_id, security_id, folio_id
        )

    async def clear(
        self, investor_id: int, security_id: int, folio_id: int
    ) -> dict[str, Any]:
        """Clear user acknowledgement on a position."""
        return await self._service.clear_acknowledgement(
            investor_id, security_id, folio_id
        )


class SymbolsResource(_BaseResource):
    """Resource sub-client for demat trading symbol resolution."""

    def __init__(self, client: FoliomanClient, service: EquitySymbolService) -> None:
        super().__init__(client)
        self._service = service

    async def resolve(
        self,
        *,
        dry_run: bool = False,
        backfill: bool = False,
        force_backfill: bool = False,
    ) -> dict[str, Any]:
        """Resolve missing NSE/BSE symbols for held demat securities."""
        return await self._service.resolve_symbols(
            dry_run=dry_run, backfill=backfill, force_backfill=force_backfill
        )


class CorporateActionsResource(_BaseResource):
    """Resource sub-client for corporate actions (bonuses, splits)."""

    def __init__(self, client: FoliomanClient, service: CorporateActionService) -> None:
        super().__init__(client)
        self._service = service

    async def refresh(
        self,
        *,
        security_ids: list[int] | None = None,
        since_year: int = 2016,
    ) -> dict[str, Any]:
        """Fetch and cache corporate action history from exchange feeds."""
        return await self._service.refresh_corporate_actions(
            security_ids=security_ids, since_year=since_year
        )

    async def list(
        self,
        *,
        security_id: int | None = None,
        isin: str | None = None,
        symbol: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List cached corporate action announcements."""
        return await self._service.list_references(
            security_id=security_id, isin=isin, symbol=symbol, kind=kind
        )

    async def apply(
        self,
        investor_id: int,
        folio_id: int,
        reference_id: int,
    ) -> dict[str, Any]:
        """Apply a cached bonus or split event to an investor folio."""
        return await self._service.apply_corporate_action(
            investor_id, folio_id, reference_id
        )


class FoliomanClient:
    """Embedded Python portfolio manager and client for Folioman services.

    Handles database management, statement imports, pricing feeds, and background jobs.

    Example:
        ```python
        import asyncio
        from folioman_client import FoliomanClient

        async def main() -> None:
            async with FoliomanClient(database_url="sqlite+aiosqlite:///folioman.db") as client:
                res = await client.imports.cas_pdf("cams_cas.pdf", "pass123")
                print("Imported:", res["schemes"], "schemes")

        asyncio.run(main())
        ```
    """

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
        *,
        database_url: str | None = None,
        user_id: str = "default",
        start_scheduler: bool = False,
        engine: AsyncEngine | None = None,
        mode: Literal["embedded", "remote"] | None = None,
    ) -> None:
        """Initialize FoliomanClient.

        Args:
            base_url: Base URL of the Folioman REST API. If None, loaded from settings/environment.
            username: Username for API authentication. If None, loaded from settings/environment.
            password: Password for API authentication. If None, loaded from settings/environment.
            timeout: Request timeout in seconds. Defaults to 30.0.
            http_client: Optional custom httpx.AsyncClient instance for custom transport/pooling.
            database_url: SQLAlchemy connection URL (e.g. 'sqlite+aiosqlite:///folioman.db').
            user_id: Multi-tenant user or portfolio identifier. Defaults to 'default'.
            start_scheduler: If True, starts an in-process thread scheduler for 6-hourly NAV refreshes.
            engine: Optional pre-configured SQLAlchemy AsyncEngine.
            mode: Explicit execution mode ('embedded' or 'remote'). Inferred from base_url if omitted.
        """
        self.base_url = (base_url or default_settings.base_url).rstrip("/")
        self.username = username if username is not None else default_settings.username
        self.password = password if password is not None else default_settings.password
        self.timeout = timeout
        self.user_id = user_id
        self._start_scheduler_flag = start_scheduler

        # Infer mode: if base_url explicitly provided, treat as remote, else embedded
        if mode is not None:
            self.mode = mode
        else:
            self.mode = "remote" if base_url else "embedded"
        self.is_remote = self.mode == "remote"

        # DB Engine & Internal Services
        self._owns_engine = engine is None
        self.engine = engine or create_folioman_engine(database_url)
        self._import_service = CASImportService(engine=self.engine)
        self._nav_service = NAVService(engine=self.engine)
        self._isin_service = ISINService(engine=self.engine)
        self._scheduler = (
            FoliomanScheduler(engine=self.engine) if start_scheduler else None
        )
        self._ledger_service = LedgerService(engine=self.engine)
        self._reconcile_service = ReconciliationService(engine=self.engine)
        self._symbol_service = EquitySymbolService(engine=self.engine)
        self._ca_service = CorporateActionService(engine=self.engine)
        self._valuation_service = ValuationService(engine=self.engine)
        self._capital_gains_service = CapitalGainsService(engine=self.engine)

        self._auth = JWTAuthManager(
            base_url=self.base_url,
            username=self.username,
            password=self.password,
        )

        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

        # Core ledger and position management
        self.investors = InvestorsResource(self)
        self.portfolio = PortfolioResource(self)
        self.holdings = HoldingsResource(self)
        self.transactions = TransactionsResource(self)
        self.folios = FoliosResource(self, self._ledger_service)
        self.valuations = ValuationsResource(self)
        self.capital_gains = CapitalGainsResource(self)

        # Embedded services
        self.imports = ImportsResource(self, self._import_service)
        self.navs = NavsResource(self, self._nav_service)
        self.isin = ISINResource(self, self._isin_service)
        self.reconcile = ReconcileResource(self, self._reconcile_service)
        self.symbols = SymbolsResource(self, self._symbol_service)
        self.corporate_actions = CorporateActionsResource(self, self._ca_service)
        self.ledger = self._ledger_service
        self.valuation_service = self._valuation_service
        self.capital_gains_service = self._capital_gains_service

    @classmethod
    def from_settings(cls, settings: FoliomanSettings) -> FoliomanClient:
        """Create a client instance from a FoliomanSettings object.

        Args:
            settings: FoliomanSettings configuration object.

        Returns:
            A configured FoliomanClient instance.
        """
        return cls(
            base_url=settings.base_url,
            username=settings.username,
            password=settings.password,
            timeout=settings.timeout,
            database_url=settings.resolved_database_url,
            user_id=settings.user_id,
        )

    @classmethod
    def from_env(cls) -> FoliomanClient:
        """Create a client instance using environment variables.

        Returns:
            A configured FoliomanClient instance using environment defaults.
        """
        return cls.from_settings(FoliomanSettings())

    async def __aenter__(self) -> FoliomanClient:
        """Enter the async context manager and start scheduler if configured."""
        if self._scheduler and not self._scheduler.is_running:
            self._scheduler.start(blocking=False)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the async context manager, stopping scheduler and closing transports."""
        await self.close()

    async def close(self) -> None:
        """Close HTTP transport, stop background scheduler, and dispose DB engine if owned."""
        if self._scheduler and self._scheduler.is_running:
            self._scheduler.shutdown()
        if self._owns_engine and self.engine is not None:
            await self.engine.dispose()
        if self._owns_http_client:
            await self._http_client.aclose()

    def _normalize_path(self, path: str) -> str:
        """Ensure path starts with /api prefix as required by Folioman API.

        Args:
            path: Relative API path string.

        Returns:
            Normalized path starting with '/api/'.
        """
        path = path.strip()
        if not path.startswith("/"):
            path = f"/{path}"
        if not path.startswith("/api/"):
            path = f"/api{path}"
        return path

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute an authenticated HTTP request with automatic token refresh and 401 retry.

        Args:
            method: HTTP method ("GET", "POST", etc.)
            path: Relative API path (e.g. "/investors/1")
            params: Optional query parameters.
            json: Optional JSON request payload.
            headers: Optional extra headers.
            **kwargs: Additional keyword arguments passed to httpx.AsyncClient.request.

        Returns:
            Parsed JSON response, or None if status code is 204 or body is empty.

        Raises:
            FoliomanNotFoundError: If response is 404.
            FoliomanAuthError: If authentication fails or refresh is rejected.
            FoliomanAPIError: If server responds with other 4xx or 5xx status codes.
        """
        normalized_path = self._normalize_path(path)
        req_headers = dict(headers or {})

        # Obtain valid Bearer token
        token = await self._auth.get_valid_token(self._http_client)
        req_headers["Authorization"] = f"Bearer {token}"

        response = await self._http_client.request(
            method=method,
            url=normalized_path,
            params=params,
            json=json,
            headers=req_headers,
            **kwargs,
        )

        # Reactive refresh if 401 Unauthorized occurs
        if response.status_code == 401:
            new_token = await self._auth.force_refresh(self._http_client)
            req_headers["Authorization"] = f"Bearer {new_token}"
            response = await self._http_client.request(
                method=method,
                url=normalized_path,
                params=params,
                json=json,
                headers=req_headers,
                **kwargs,
            )

        return self._handle_response(response, normalized_path)

    def _handle_response(self, response: httpx.Response, path: str) -> Any:
        """Process HTTP response, translating errors to Folioman client exceptions.

        Args:
            response: httpx.Response object.
            path: Normalized path requested.

        Returns:
            Parsed response JSON or None.

        Raises:
            FoliomanNotFoundError: If response status is 404.
            FoliomanAuthError: If response status is 401.
            FoliomanAPIError: If response status is not successful or parsing fails.
        """
        if response.status_code == 404:
            raise FoliomanNotFoundError(f"Resource not found at {path}")

        if response.status_code == 401:
            raise FoliomanAuthError(f"Authentication failed for {path} (HTTP 401)")

        if not response.is_success:
            detail: Any = None
            try:
                data = response.json()
                detail = data.get("detail", data)
            except Exception:
                detail = response.text
            raise FoliomanAPIError(
                message=f"Folioman API error on {response.request.method} {path}: {detail}",
                status_code=response.status_code,
                response_data=detail,
            )

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except Exception as exc:
            raise FoliomanAPIError(
                message=f"Failed to parse JSON response from {path}: {exc}",
                status_code=response.status_code,
                response_data=response.text,
            ) from exc


__all__ = [
    "FoliomanClient",
    "InvestorsResource",
    "PortfolioResource",
    "HoldingsResource",
    "TransactionsResource",
    "ValuationsResource",
    "CapitalGainsResource",
    "ImportsResource",
    "NavsResource",
    "ISINResource",
    "FoliosResource",
    "ReconcileResource",
    "SymbolsResource",
    "CorporateActionsResource",
]
