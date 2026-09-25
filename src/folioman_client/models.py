"""Pydantic models representing Folioman API schemas.

These models mirror the OpenAPI contracts in Folioman (v1).
All models use extra="ignore" to remain resilient against future schema extensions.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from folioman_client.types import (
    ConfiguredDate,
    ConfiguredDatetime,
    ConfiguredDecimal,
)


class FoliomanBaseModel(BaseModel):
    """Base model with common configuration for all Folioman models.

    Ignores extra keys sent by the API for forward compatibility and
    supports field population by name.
    """

    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


# --- Auth Models ---
class TokenPair(FoliomanBaseModel):
    """Access and refresh token pair returned on authentication.

    Attributes:
        access: Short-lived JWT bearer token used for authorizing requests.
        refresh: Long-lived refresh token used to obtain renewed access tokens.
    """

    access: str
    refresh: str


class AccessToken(FoliomanBaseModel):
    """Refreshed access token.

    Attributes:
        access: Newly minted short-lived JWT bearer token.
    """

    access: str


# --- Investor Models ---
class Investor(FoliomanBaseModel):
    """Investor summary representation.

    Attributes:
        id: Unique numeric identifier of the investor.
        name: Full legal name or display name of the investor.
        email: Contact email address of the investor.
        is_huf: Whether the investor represents a Hindu Undivided Family.
        relation: Relationship description if part of a family group.
        family_id: ID of the parent family group, if affiliated.
        has_pan: Whether a Permanent Account Number is registered.
        pan_locked: Whether PAN changes are locked for compliance.
        created_at: Timestamp when the investor record was created.
        updated_at: Timestamp when the investor record was last updated.
    """

    id: int
    name: str
    email: str = ""
    is_huf: bool = False
    relation: str = ""
    family_id: int | None = None
    has_pan: bool = False
    pan_locked: bool = False
    created_at: ConfiguredDatetime | None = None
    updated_at: ConfiguredDatetime | None = None


class InvestorDetail(Investor):
    """Investor detailed representation with masked PAN.

    Attributes:
        pan_masked: Masked PAN string (e.g. 'ABCDE****F') protecting sensitive PII.
    """

    pan_masked: str = ""


# --- Holding & Security Models ---
class Holding(FoliomanBaseModel):
    """Priced holding row under an investor.

    Attributes:
        security_id: Unique identifier for the underlying security/scheme.
        name: Name of the security or mutual fund scheme.
        security_type: Category of the security (e.g., 'MF', 'EQUITY').
        symbol: Ticker symbol or trading identifier.
        amc: Asset Management Company name.
        category: SEBI category or mutual fund classification.
        units: Total quantity of units held.
        value_inr: Current market valuation in INR.
        invested_inr: Total invested amount (cost basis) in INR.
        latest_nav: Latest available Net Asset Value.
        return_pct: Absolute percentage return.
        xirr: Extended Internal Rate of Return (annualized).
        day_change_inr: Monetary change in valuation since the previous trading day.
        day_change_pct: Percentage change since the previous trading day.
    """

    security_id: int
    name: str
    security_type: str
    symbol: str = ""
    amc: str = ""
    category: str = ""
    units: ConfiguredDecimal
    value_inr: ConfiguredDecimal | None = None
    invested_inr: ConfiguredDecimal | None = None
    latest_nav: ConfiguredDecimal | None = None
    return_pct: float | None = None
    xirr: float | None = None
    day_change_inr: ConfiguredDecimal | None = None
    day_change_pct: float | None = None


class SchemeRef(FoliomanBaseModel):
    """Security identity metadata.

    Attributes:
        id: Unique identifier of the security.
        name: Full name of the mutual fund scheme or security.
        isin: International Securities Identification Number.
        symbol: Ticker symbol if traded on an exchange.
        security_type: Type of security (e.g. 'MF', 'EQUITY').
        amfi_code: Association of Mutual Funds in India identifier.
        amc: Asset Management Company managing the scheme.
        category: Scheme investment category.
    """

    id: int
    name: str
    isin: str = ""
    symbol: str = ""
    security_type: str = ""
    amfi_code: str = ""
    amc: str | None = None
    category: str | None = None


class NavPoint(FoliomanBaseModel):
    """Single date and NAV point.

    Attributes:
        date: Valuation date for the NAV point.
        nav: Net Asset Value per unit on the specified date.
    """

    date: ConfiguredDate
    nav: ConfiguredDecimal


class FolioBalance(FoliomanBaseModel):
    """Balance for one folio holding a security.

    Attributes:
        number: Folio account number.
        broker: Broker / ARN identifier associated with the folio.
        folio_type: Type classification of the folio account.
        units: Unit balance held under this folio.
        value_inr: Monetary valuation in INR for this folio.
    """

    number: str
    broker: str = ""
    folio_type: str = ""
    units: ConfiguredDecimal
    value_inr: ConfiguredDecimal | None = None


# --- Transaction Models ---
class Transaction(FoliomanBaseModel):
    """Transaction ledger record.

    Attributes:
        id: Unique numeric identifier for the transaction record.
        investor_id: ID of the investor who owns the holding.
        security_id: ID of the security being traded.
        folio_id: ID of the folio account if linked.
        date: Effective transaction date.
        transaction_type: Transaction category (e.g., 'PURCHASE', 'REDEMPTION', 'SIP').
        units: Number of units transacted.
        nav_or_price: Unit price or NAV at which the transaction was executed.
        amount: Gross transaction amount in INR.
        fees: Fees associated with the transaction.
        stamp_duty: Mandatory stamp duty charges.
        brokerage: Brokerage commission charged.
        currency: ISO currency code (defaults to 'INR').
        source: Ingestion source or platform (e.g., 'CAMS', 'KFintech').
        narration: Descriptive ledger text or note.
        cost_basis_complete: Flag indicating whether cost basis is known.
        via_security: Auxiliary security reference for switches.
        balance: Cumulative unit balance following this transaction.
    """

    id: int
    investor_id: int
    security_id: int
    folio_id: int | None = None
    date: ConfiguredDate
    transaction_type: str
    units: ConfiguredDecimal
    nav_or_price: ConfiguredDecimal
    amount: ConfiguredDecimal | None = None
    fees: ConfiguredDecimal = Decimal("0")
    stamp_duty: ConfiguredDecimal = Decimal("0")
    brokerage: ConfiguredDecimal = Decimal("0")
    currency: str = "INR"
    source: str = ""
    narration: str = ""
    cost_basis_complete: bool = True
    via_security: str | None = None
    balance: ConfiguredDecimal | None = None


class SchemeDetail(FoliomanBaseModel):
    """Detailed scheme view for an investor.

    Attributes:
        security: Scheme metadata reference.
        as_of: Point-in-time calculation date.
        units: Total units held across all folios.
        value_inr: Current market value in INR.
        invested_inr: Total cost basis in INR.
        return_pct: Absolute return percentage.
        xirr: Annualized internal rate of return.
        xirr_status: Status indicator for XIRR calculation convergence.
        day_change_inr: Valuation change compared to previous trading day.
        day_change_pct: Percentage change compared to previous trading day.
        latest_nav: Most recent recorded Net Asset Value.
        latest_nav_date: Date of the latest NAV record.
        has_transactions: Whether transaction records are available.
        partial_history: Whether historical records are incomplete.
        partial_history_from: Starting date of available history if partial.
        folios: Breakdown of units across individual folios.
        nav_history: Time series of historical NAV points.
        transactions: Ledger of historical transactions for this scheme.
    """

    security: SchemeRef
    as_of: ConfiguredDate
    units: ConfiguredDecimal
    value_inr: ConfiguredDecimal | None = None
    invested_inr: ConfiguredDecimal | None = None
    return_pct: float | None = None
    xirr: float | None = None
    xirr_status: str = ""
    day_change_inr: ConfiguredDecimal | None = None
    day_change_pct: float | None = None
    latest_nav: ConfiguredDecimal | None = None
    latest_nav_date: ConfiguredDate | None = None
    has_transactions: bool = False
    partial_history: bool = False
    partial_history_from: ConfiguredDate | None = None
    folios: list[FolioBalance] = Field(default_factory=list)
    nav_history: list[NavPoint] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)


# --- Portfolio & Valuation Models ---
class AssetMixRow(FoliomanBaseModel):
    """Allocation breakdown row by security type.

    Attributes:
        security_type: Asset class label (e.g. 'EQUITY', 'DEBT', 'CASH').
        value_inr: Total valuation allocated to this security type in INR.
    """

    security_type: str
    value_inr: ConfiguredDecimal


class AllocationBucket(FoliomanBaseModel):
    """Allocation breakdown row by AMC or category.

    Attributes:
        label: AMC name or category classification label.
        value_inr: Total valuation allocated to this bucket in INR.
    """

    label: str
    value_inr: ConfiguredDecimal


class PeriodReturn(FoliomanBaseModel):
    """Trailing window money-weighted return (1M, 1Y, All, etc.).

    Attributes:
        period: Label for the trailing window (e.g. '1M', '3M', '1Y', 'ALL').
        annualized: Annualized internal rate of return for the period.
        absolute: Absolute percentage return for the period.
        days: Number of calendar days in the evaluation window.
    """

    period: str
    annualized: float
    absolute: float | None = None
    days: int


class PortfolioSummary(FoliomanBaseModel):
    """Overall portfolio summary for an investor (InvestorSummaryOut).

    Attributes:
        investor_id: Unique identifier of the investor.
        as_of: Valuation date of the portfolio summary.
        total_inr: Aggregate portfolio valuation in INR.
        is_provisional: Flag indicating if pricing is provisional or final.
        navs_as_of: Effective date of NAV points used in this valuation.
        navs_stale: True if latest NAVs have not been updated recently.
        holdings_count: Total count of active holdings.
        integrity_unit_count: Count of holdings with verified unit balances.
        tax_ready_count: Count of holdings with reconciled tax lots.
        needs_attention_count: Holdings requiring advisor intervention.
        snapshot_count: Number of historical snapshots available.
        stale_count: Number of unpriced or stale holdings.
        unpriced_fund_count: Number of holdings without available NAV.
        last_import_at: Timestamp of the most recent data import.
        day_change_inr: Monetary change since previous business day.
        xirr: Overall portfolio annualized internal rate of return.
        period_returns: Trailing performance metrics across windows.
        asset_mix: Asset class breakdown (Equity, Debt, Cash, etc.).
        amc_mix: Asset Management Company distribution breakdown.
        category_mix: Mutual fund category distribution breakdown.
        top_holdings: Subset of top holdings by value.
        holdings: Full list of priced holdings for this investor.
    """

    investor_id: int
    as_of: ConfiguredDate
    total_inr: ConfiguredDecimal
    is_provisional: bool = False
    navs_as_of: ConfiguredDate | None = None
    navs_stale: bool = False
    holdings_count: int = 0
    integrity_unit_count: int = 0
    tax_ready_count: int = 0
    needs_attention_count: int = 0
    snapshot_count: int = 0
    stale_count: int = 0
    unpriced_fund_count: int = 0
    last_import_at: ConfiguredDatetime | None = None
    day_change_inr: ConfiguredDecimal | None = None
    xirr: float | None = None
    period_returns: list[PeriodReturn] = Field(default_factory=list)
    asset_mix: list[AssetMixRow] = Field(default_factory=list)
    amc_mix: list[AllocationBucket] = Field(default_factory=list)
    category_mix: list[AllocationBucket] = Field(default_factory=list)
    top_holdings: list[Holding] = Field(default_factory=list)
    holdings: list[Holding] = Field(default_factory=list)


class ValueSeriesPoint(FoliomanBaseModel):
    """Single date point in net worth valuation series.

    Attributes:
        date: Valuation point date.
        value_inr: Total portfolio value in INR on this date.
        invested_inr: Cumulative invested capital in INR on this date.
        stale: Whether the valuation data for this date is stale.
    """

    date: ConfiguredDate
    value_inr: ConfiguredDecimal
    invested_inr: ConfiguredDecimal
    stale: bool = False


class ValueSeries(FoliomanBaseModel):
    """Reconstructed net-worth-over-time time series.

    Attributes:
        investor_id: Optional investor ID filter.
        family_id: Optional family ID filter.
        start: Start date of the time series.
        end: End date of the time series.
        granularity: Sampling frequency ('daily', 'weekly', 'monthly').
        points: Ordered list of valuation time series points.
    """

    investor_id: int | None = None
    family_id: int | None = None
    start: ConfiguredDate
    end: ConfiguredDate
    granularity: str
    points: list[ValueSeriesPoint] = Field(default_factory=list)


class ValuationStatus(FoliomanBaseModel):
    """Valuation calculation readiness status.

    Attributes:
        investor_id: ID of the investor.
        family_id: ID of the family group if applicable.
        status: Engine readiness status (e.g. 'READY', 'COMPUTING', 'ERROR').
        computed_through: Date up to which valuations have been finalized.
        recompute_from: Earliest date from which recalculation is needed.
        is_provisional: Whether the current numbers are provisional.
    """

    investor_id: int | None = None
    family_id: int | None = None
    status: str
    computed_through: ConfiguredDate | None = None
    recompute_from: ConfiguredDate | None = None
    is_provisional: bool = False


# --- Capital Gains Models ---
class CapitalGainRow(FoliomanBaseModel):
    """One realised disposal lot in capital gains report.

    Attributes:
        security_id: ID of the security redeemed or sold.
        name: Name of the security or mutual fund scheme.
        isin: ISIN code of the security.
        units: Number of units redeemed or disposed.
        sale_value: Realized sale proceeds in INR.
        cost: Indexed or purchase cost basis in INR.
        gain: Realized capital gain or loss in INR.
        term: Classification of gain ('STCG' or 'LTCG').
        acquired_on: Original purchase date of the lot.
        sold_on: Date of disposal or redemption.
        grandfathering_unavailable: Whether Section 112A grandfathering is unavailable.
    """

    security_id: int | None = None
    name: str
    isin: str = ""
    units: ConfiguredDecimal
    sale_value: ConfiguredDecimal
    cost: ConfiguredDecimal
    gain: ConfiguredDecimal
    term: str
    acquired_on: ConfiguredDate
    sold_on: ConfiguredDate
    grandfathering_unavailable: bool = False


class CapitalGainsReport(FoliomanBaseModel):
    """Realised capital gains report for a financial year (CapitalGainsOut).

    Attributes:
        fy: Financial year label (e.g., '2024-25').
        stcg_total: Total realized Short-Term Capital Gains in INR.
        ltcg_total: Total realized Long-Term Capital Gains in INR.
        rows: Detailed breakdown of individual disposal lots.
        disclaimer: Legal or regulatory tax disclaimer text.
    """

    fy: str
    stcg_total: ConfiguredDecimal
    ltcg_total: ConfiguredDecimal
    rows: list[CapitalGainRow] = Field(default_factory=list)
    disclaimer: str = ""


class CapitalGainsFyPoint(FoliomanBaseModel):
    """Year-over-year capital gains summary point.

    Attributes:
        fy: Financial year label (e.g., '2023-24').
        stcg: Total realized STCG for the year.
        ltcg: Total realized LTCG for the year.
    """

    fy: str
    stcg: ConfiguredDecimal
    ltcg: ConfiguredDecimal


__all__ = [
    "FoliomanBaseModel",
    "TokenPair",
    "AccessToken",
    "Investor",
    "InvestorDetail",
    "Holding",
    "SchemeRef",
    "NavPoint",
    "FolioBalance",
    "Transaction",
    "SchemeDetail",
    "AssetMixRow",
    "AllocationBucket",
    "PeriodReturn",
    "PortfolioSummary",
    "ValueSeriesPoint",
    "ValueSeries",
    "ValuationStatus",
    "CapitalGainRow",
    "CapitalGainsReport",
    "CapitalGainsFyPoint",
    "ConfiguredDecimal",
    "ConfiguredDate",
    "ConfiguredDatetime",
]
