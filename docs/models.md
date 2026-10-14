# Data Models & Serialization Types

`folioman-client` models are built on Pydantic v2. They parse JSON responses and database records into strongly-typed, immutable, validated Python data structures.

All models inherit from `FoliomanBaseModel`, configured with `extra="ignore"` and `populate_by_name=True`. This design guarantees that if newer versions of the engine or upstream APIs return additional fields, your existing client code will never crash.

---

## Custom Serialization Types

In portfolio accounting and tax computations, standard floating-point numbers (`0.1 + 0.2 = 0.30000000000000004`) introduce precision errors that can invalidate unit reconciliation or tax calculations. 

To prevent this, `folioman-client` provides annotated types in `folioman_client.types`:

```python
from folioman_client.types import (
    ConfiguredDecimal,
    ConfiguredDate,
    ConfiguredDatetime,
)
```

| Type Alias | Python Runtime Type | JSON Output | Description |
| :--- | :--- | :--- | :--- |
| `ConfiguredDecimal` | `decimal.Decimal` | `float` (or `None`) | Preserves exact fixed-point arithmetic in Python calculations while serializing cleanly to standard JSON floats for UI charts or APIs. |
| `ConfiguredDate` | `datetime.date` | `str` (`YYYY-MM-DD`) | Strictly validates calendar dates and serializes to ISO-8601 date strings. |
| `ConfiguredDatetime` | `datetime.datetime` | `str` (ISO-8601) | Represents exact UTC timestamps and serializes to standard ISO-8601 strings. |

---

## Models Reference

### 1. Authentication Models

#### `TokenPair`
Returned when authenticating against a remote Folioman server.

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `access` | `str` | Yes | Short-lived JWT bearer token used for authorized requests. |
| `refresh` | `str` | Yes | Long-lived refresh token used to obtain renewed access tokens. |

#### `AccessToken`
Returned when refreshing an access token.

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `access` | `str` | Yes | Newly minted short-lived JWT bearer token. |

---

### 2. Investor Models

#### `Investor`
Summary representation of an individual investor or HUF entity.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `int` | Yes | — | Unique numeric investor ID. |
| `name` | `str` | Yes | — | Full legal or display name of the investor. |
| `email` | `str` | No | `""` | Contact email address. |
| `is_huf` | `bool` | No | `False` | True if the account is a Hindu Undivided Family. |
| `relation` | `str` | No | `""` | Relationship label if grouped into a family account (e.g. `Primary`, `Spouse`). |
| `family_id` | `int \| None` | No | `None` | Associated family group ID, if affiliated. |
| `has_pan` | `bool` | No | `False` | True if an encrypted PAN is stored for this investor. |
| `pan_locked` | `bool` | No | `False` | True if PAN modifications are locked for compliance. |
| `created_at` | `ConfiguredDatetime \| None` | No | `None` | Timestamp when investor record was created. |
| `updated_at` | `ConfiguredDatetime \| None` | No | `None` | Timestamp when investor record was last updated. |

#### `InvestorDetail`
Inherits all attributes from `Investor`, adding:

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `pan_masked` | `str` | No | `""` | Masked PAN string (e.g., `ABCDE****F`) protecting personal information. |

---

### 3. Portfolio & Allocation Models

#### `PortfolioSummary`
Comprehensive portfolio valuation summary and health report for an investor.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `investor_id` | `int` | Yes | — | Investor ID. |
| `as_of` | `ConfiguredDate` | Yes | — | Valuation date. |
| `total_inr` | `ConfiguredDecimal` | Yes | — | Aggregate market value across all active holdings in INR. |
| `is_provisional` | `bool` | No | `False` | True if NAVs or prices are still updating for the day. |
| `navs_as_of` | `ConfiguredDate \| None` | No | `None` | Effective date of the latest NAV quotes used. |
| `navs_stale` | `bool` | No | `False` | True if quotes are older than the previous trading session. |
| `holdings_count` | `int` | No | `0` | Total count of active holdings. |
| `integrity_unit_count` | `int` | No | `0` | Count of holdings with verified balance checks. |
| `tax_ready_count` | `int` | No | `0` | Count of holdings where all trade lots are reconciled and tax-safe. |
| `needs_attention_count` | `int` | No | `0` | Holdings requiring user attention (e.g. unit mismatches). |
| `snapshot_count` | `int` | No | `0` | Number of historical statement snapshots on file. |
| `stale_count` | `int` | No | `0` | Number of unpriced or stale holdings. |
| `unpriced_fund_count` | `int` | No | `0` | Number of mutual funds lacking a current NAV quote. |
| `last_import_at` | `ConfiguredDatetime \| None` | No | `None` | Timestamp of the most recent statement import. |
| `day_change_inr` | `ConfiguredDecimal \| None` | No | `None` | Monetary change in portfolio value compared to previous business day. |
| `xirr` | `float \| None` | No | `None` | Overall money-weighted annualized return (e.g. `0.142` for 14.2%). |
| `period_returns` | `list[PeriodReturn]` | No | `[]` | Trailing window performance metrics (1M, 3M, 1Y, 3Y, ALL). |
| `asset_mix` | `list[AssetMixRow]` | No | `[]` | Asset class breakdown (Equity, Debt, Cash, etc.). |
| `amc_mix` | `list[AllocationBucket]` | No | `[]` | Distribution breakdown by Asset Management Company. |
| `category_mix` | `list[AllocationBucket]` | No | `[]` | Distribution breakdown by SEBI mutual fund category. |
| `top_holdings` | `list[Holding]` | No | `[]` | Top holdings sorted by market valuation. |
| `holdings` | `list[Holding]` | No | `[]` | Complete list of priced holdings. |

#### `AssetMixRow`
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `security_type` | `str` | Yes | Asset class label (e.g., `'MF'`, `'EQUITY'`, `'GOLD'`, `'CASH'`). |
| `value_inr` | `ConfiguredDecimal` | Yes | Monetary valuation in INR allocated to this class. |

#### `AllocationBucket`
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | Yes | Name of the bucket (e.g. `"HDFC AMC"` or `"Flexi Cap Fund"`). |
| `value_inr` | `ConfiguredDecimal` | Yes | Monetary valuation in INR allocated to this bucket. |

#### `PeriodReturn`
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `period` | `str` | Yes | Trailing evaluation window (e.g. `'1M'`, `'3M'`, `'6M'`, `'1Y'`, `'3Y'`, `'ALL'`). |
| `annualized` | `float` | Yes | Annualized money-weighted rate of return (XIRR). |
| `absolute` | `float \| None` | No | Absolute percentage change over the evaluation window. |
| `days` | `int` | Yes | Calendar days included in the evaluation window. |

---

### 4. Holding & Security Models

#### `Holding`
Priced position row under an investor.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `security_id` | `int` | Yes | — | Identifier of the security/scheme. |
| `name` | `str` | Yes | — | Full scheme or company name. |
| `security_type` | `str` | Yes | — | Asset type (e.g. `'MF'`, `'EQUITY'`, `'ETF'`). |
| `symbol` | `str` | No | `""` | NSE/BSE trading ticker symbol. |
| `amc` | `str` | No | `""` | Asset Management Company name. |
| `category` | `str` | No | `""` | SEBI investment category. |
| `units` | `ConfiguredDecimal` | Yes | — | Quantity of units held. |
| `value_inr` | `ConfiguredDecimal \| None` | No | `None` | Current market value in INR. |
| `invested_inr` | `ConfiguredDecimal \| None` | No | `None` | Cumulative cost basis (invested capital) in INR. |
| `latest_nav` | `ConfiguredDecimal \| None` | No | `None` | Latest recorded Net Asset Value or share price. |
| `return_pct` | `float \| None` | No | `None` | Absolute return percentage (`(value - cost) / cost`). |
| `xirr` | `float \| None` | No | `None` | Annualized money-weighted rate of return for this holding. |
| `day_change_inr` | `ConfiguredDecimal \| None` | No | `None` | Monetary change in valuation since previous trading day. |
| `day_change_pct` | `float \| None` | No | `None` | Percentage change since previous trading day. |

#### `SchemeRef`
Metadata identifying a mutual fund scheme or traded equity.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `int` | Yes | — | Security ID. |
| `name` | `str` | Yes | — | Full scheme or company name. |
| `isin` | `str` | No | `""` | 12-character ISIN code. |
| `symbol` | `str` | No | `""` | Exchange ticker symbol. |
| `security_type` | `str` | No | `""` | Asset type classification. |
| `amfi_code` | `str` | No | `""` | 6-digit AMFI code. |
| `amc` | `str \| None` | No | `None` | Asset Management Company name. |
| `category` | `str \| None` | No | `None` | SEBI category classification. |

#### `NavPoint`
Single historical pricing point.

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `date` | `ConfiguredDate` | Yes | Valuation date. |
| `nav` | `ConfiguredDecimal` | Yes | Net Asset Value or closing price per unit. |

#### `FolioBalance`
Unit breakdown in an individual folio account holding a security.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `number` | `str` | Yes | — | Folio or demat account number. |
| `broker` | `str` | No | `""` | Broker name or distributor ARN code. |
| `folio_type` | `str` | No | `""` | Folio type (e.g. `'regular'`, `'direct'`, `'demat'`). |
| `units` | `ConfiguredDecimal` | Yes | — | Unit balance held in this folio. |
| `value_inr` | `ConfiguredDecimal \| None` | No | `None` | Monetary valuation in INR for this folio. |

#### `SchemeDetail`
Deep inspection report for a specific holding, including historical NAV curve, folio breakdown, and transaction ledger.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `security` | `SchemeRef` | Yes | — | Security identity metadata. |
| `as_of` | `ConfiguredDate` | Yes | — | Valuation calculation date. |
| `units` | `ConfiguredDecimal` | Yes | — | Total units held across all folios. |
| `value_inr` | `ConfiguredDecimal \| None` | No | `None` | Total market valuation in INR. |
| `invested_inr` | `ConfiguredDecimal \| None` | No | `None` | Cumulative cost basis in INR. |
| `return_pct` | `float \| None` | No | `None` | Absolute return percentage. |
| `xirr` | `float \| None` | No | `None` | Annualized money-weighted rate of return. |
| `xirr_status` | `str` | No | `""` | Status indicator for XIRR calculation convergence. |
| `day_change_inr` | `ConfiguredDecimal \| None` | No | `None` | Valuation change compared to previous trading day. |
| `day_change_pct` | `float \| None` | No | `None` | Percentage change compared to previous trading day. |
| `latest_nav` | `ConfiguredDecimal \| None` | No | `None` | Most recent recorded Net Asset Value. |
| `latest_nav_date` | `ConfiguredDate \| None` | No | `None` | Date of the latest recorded NAV. |
| `has_transactions` | `bool` | No | `False` | True if transaction records exist for this scheme. |
| `partial_history` | `bool` | No | `False` | True if statement history starts with non-zero opening balance. |
| `partial_history_from`| `ConfiguredDate \| None` | No | `None` | Starting date of available history if partial. |
| `folios` | `list[FolioBalance]` | No | `[]` | Unit breakdown across individual folios. |
| `nav_history` | `list[NavPoint]` | No | `[]` | Historical NAV series for performance charting. |
| `transactions` | `list[Transaction]` | No | `[]` | Chronological transaction ledger for this scheme. |

---

### 5. Transactions & Ledger Models

#### `Transaction`
Immutable ledger record of an executed financial event.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `int` | Yes | — | Unique numeric ledger transaction ID. |
| `investor_id` | `int` | Yes | — | ID of the investor who owns the transaction. |
| `security_id` | `int` | Yes | — | ID of the traded security. |
| `folio_id` | `int \| None` | No | `None` | ID of the folio account if linked. |
| `date` | `ConfiguredDate` | Yes | — | Effective trade execution date. |
| `transaction_type` | `str` | Yes | — | Action type (`PURCHASE`, `REDEMPTION`, `SIP`, `SWITCH_IN`, `SWITCH_OUT`, `BONUS`, `SPLIT`, `DIVIDEND_PAYOUT`). |
| `units` | `ConfiguredDecimal` | Yes | — | Quantity of units transacted. |
| `nav_or_price` | `ConfiguredDecimal` | Yes | — | Executed NAV or share price. |
| `amount` | `ConfiguredDecimal \| None` | No | `None` | Gross monetary amount in INR. |
| `fees` | `ConfiguredDecimal` | No | `0` | Transaction fees charged. |
| `stamp_duty` | `ConfiguredDecimal` | No | `0` | Government stamp duty paid. |
| `brokerage` | `ConfiguredDecimal` | No | `0` | Brokerage commission paid. |
| `currency` | `str` | No | `"INR"` | Currency ISO code. |
| `source` | `str` | No | `""` | Statement ingestion source (e.g. `'CAMS'`, `'KFintech'`, `'CDSL'`). |
| `narration` | `str` | No | `""` | Original transaction narration text from statement. |
| `cost_basis_complete` | `bool` | No | `True` | Flag indicating whether historical purchase price is known. |
| `via_security` | `str \| None` | No | `None` | Paired security identifier for switches or transfers. |
| `balance` | `ConfiguredDecimal \| None` | No | `None` | Cumulative running unit balance after this transaction. |

---

### 6. Valuations & Series Models

#### `ValueSeriesPoint`
Single date point in a historical net worth time series.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `date` | `ConfiguredDate` | Yes | — | Valuation date. |
| `value_inr` | `ConfiguredDecimal` | Yes | — | Total portfolio market value in INR on this date. |
| `invested_inr` | `ConfiguredDecimal` | Yes | — | Cumulative invested capital (cost basis) in INR on this date. |
| `stale` | `bool` | No | `False` | True if quotes for any held security were carried forward from prior days. |

#### `ValueSeries`
Historical net worth time series output.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `investor_id` | `int \| None` | No | `None` | Filtered investor ID. |
| `family_id` | `int \| None` | No | `None` | Filtered family ID. |
| `start` | `ConfiguredDate` | Yes | — | Series start date. |
| `end` | `ConfiguredDate` | Yes | — | Series end date. |
| `granularity` | `str` | Yes | — | Sampling frequency (`'daily'`, `'weekly'`, `'monthly'`). |
| `points` | `list[ValueSeriesPoint]` | No | `[]` | Chronological list of historical valuation points. |

#### `ValuationStatus`
Indicates current engine state and coverage of valuation calculations.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `investor_id` | `int \| None` | No | `None` | Associated investor ID. |
| `family_id` | `int \| None` | No | `None` | Associated family ID. |
| `status` | `str` | Yes | — | Valuation state (`'READY'`, `'PENDING'`, `'COMPUTING'`, `'STALE'`). |
| `computed_through` | `ConfiguredDate \| None` | No | `None` | Latest date up to which daily valuations have been computed. |
| `recompute_from` | `ConfiguredDate \| None` | No | `None` | Earliest date requiring recomputation due to backdated trades. |
| `is_provisional` | `bool` | No | `False` | True if today's pricing has not yet closed. |

---

### 7. Capital Gains & Tax Models

#### `CapitalGainRow`
Single realized disposal lot matched using First-In, First-Out (FIFO) accounting.

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `security_id` | `int \| None` | No | `None` | ID of the disposed security. |
| `name` | `str` | Yes | — | Scheme or security name. |
| `isin` | `str` | No | `""` | 12-character ISIN code. |
| `units` | `ConfiguredDecimal` | Yes | — | Number of units redeemed or sold. |
| `sale_value` | `ConfiguredDecimal` | Yes | — | Realized gross sale proceeds in INR. |
| `cost` | `ConfiguredDecimal` | Yes | — | Deemed purchase cost in INR (reflecting Section 112A grandfathering if applicable). |
| `gain` | `ConfiguredDecimal` | Yes | — | Realized capital gain or loss in INR (`sale_value - cost`). |
| `term` | `str` | Yes | — | Tax classification: `'STCG'` (Short-Term) or `'LTCG'` (Long-Term). |
| `acquired_on` | `ConfiguredDate` | Yes | — | Date the original units were purchased. |
| `sold_on` | `ConfiguredDate` | Yes | — | Date the units were redeemed or sold. |
| `grandfathering_unavailable` | `bool` | No | `False` | True if the lot was acquired before 31-Jan-2018 but grandfathering NAV was missing. |

#### `CapitalGainsReport`
Comprehensive capital gains statement for an Indian Financial Year (1 April – 31 March).

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `fy` | `str` | Yes | — | Financial year label (e.g. `'2024-25'`). |
| `stcg_total` | `ConfiguredDecimal` | Yes | — | Total realized Short-Term Capital Gains in INR. |
| `ltcg_total` | `ConfiguredDecimal` | Yes | — | Total realized Long-Term Capital Gains in INR. |
| `rows` | `list[CapitalGainRow]` | No | `[]` | Detailed lot-level breakdown of all redemptions in this FY. |
| `disclaimer` | `str` | No | `""` | Statutory disclaimer clarifying tax assumptions and advisory notices. |

#### `CapitalGainsFyPoint`
Summary point showing annual realized gains across historical financial years.

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `fy` | `str` | Yes | Financial year label (e.g. `'2023-24'`). |
| `stcg` | `ConfiguredDecimal` | Yes | Realized STCG in INR for the year. |
| `ltcg` | `ConfiguredDecimal` | Yes | Realized LTCG in INR for the year. |
