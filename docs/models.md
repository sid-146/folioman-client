# Data Models & Serialization Types

`folioman-client` models are built on Pydantic v2. They parse JSON responses into immutable, validated Python data structures.

All models inherit from `FoliomanBaseModel`, configured with `extra="ignore"` and `populate_by_name=True`. This ensures forward compatibility when the Folioman backend introduces new fields.

---

## Custom Serialization Types

In financial systems, floating-point rounding errors can corrupt monetary balances. `folioman-client` defines annotated Pydantic types in `folioman_client.types` to manage precision safely:

```python
from folioman_client.types import (
    ConfiguredDecimal,
    ConfiguredDate,
    ConfiguredDatetime,
)
```

| Type Alias           | Python Source Type  | JSON / Serialization Output    | Description                                                                                                  |
| :------------------- | :------------------ | :----------------------------- | :----------------------------------------------------------------------------------------------------------- |
| `ConfiguredDecimal`  | `decimal.Decimal`   | `float` (unless `None`)        | Preserves decimal arithmetic precision in Python, but serializes to JSON numbers for downstream consumption. |
| `ConfiguredDate`     | `datetime.date`     | `str` (ISO-8601: `YYYY-MM-DD`) | Formats dates to standard ISO strings on serialization (`unless-none`).                                      |
| `ConfiguredDatetime` | `datetime.datetime` | `str` (ISO-8601)               | Formats timestamp to standard ISO-8601 string on serialization (`unless-none`).                              |

---

## Models Reference

### 1. Authentication Models

#### `TokenPair`

Token pair returned by `/api/auth/token/pair`.

| Field     | Type  | Required | Description                   |
| :-------- | :---- | :------- | :---------------------------- |
| `access`  | `str` | Yes      | Short-lived JWT bearer token. |
| `refresh` | `str` | Yes      | Long-lived refresh token.     |

#### `AccessToken`

Refreshed access token payload.

| Field    | Type  | Required | Description                 |
| :------- | :---- | :------- | :-------------------------- |
| `access` | `str` | Yes      | Refreshed JWT bearer token. |

---

### 2. Investor Models

#### `Investor`

Summary representation of an investor.

| Field        | Type                         | Required | Default | Description                           |
| :----------- | :--------------------------- | :------- | :------ | :------------------------------------ |
| `id`         | `int`                        | Yes      | -       | Unique investor identifier.           |
| `name`       | `str`                        | Yes      | -       | Full legal or display name.           |
| `email`      | `str`                        | No       | `""`    | Contact email address.                |
| `is_huf`     | `bool`                       | No       | `False` | Whether investor is an HUF account.   |
| `relation`   | `str`                        | No       | `""`    | Family relationship description.      |
| `family_id`  | `int \| None`                | No       | `None`  | Associated family group ID.           |
| `has_pan`    | `bool`                       | No       | `False` | Whether PAN is registered.            |
| `pan_locked` | `bool`                       | No       | `False` | Whether PAN modifications are locked. |
| `created_at` | `ConfiguredDatetime \| None` | No       | `None`  | Creation timestamp.                   |
| `updated_at` | `ConfiguredDatetime \| None` | No       | `None`  | Last modification timestamp.          |

#### `InvestorDetail`

Inherits all attributes from `Investor`, adding:

| Field        | Type  | Required | Default | Description                     |
| :----------- | :---- | :------- | :------ | :------------------------------ |
| `pan_masked` | `str` | No       | `""`    | Masked PAN (e.g. `ABCDE****F`). |

---

### 3. Portfolio & Allocation Models

#### `PortfolioSummary`

Comprehensive portfolio valuation summary.

| Field            | Type                        | Required | Default | Description                                    |
| :--------------- | :-------------------------- | :------- | :------ | :--------------------------------------------- |
| `investor_id`    | `int`                       | Yes      | -       | Investor ID.                                   |
| `as_of`          | `ConfiguredDate`            | Yes      | -       | Valuation date.                                |
| `total_inr`      | `ConfiguredDecimal`         | Yes      | -       | Total portfolio value in INR.                  |
| `is_provisional` | `bool`                      | No       | `False` | Indicates if valuation is provisional.         |
| `navs_as_of`     | `ConfiguredDate \| None`    | No       | `None`  | Effective date of underlying NAVs.             |
| `navs_stale`     | `bool`                      | No       | `False` | True if NAVs are out of date.                  |
| `holdings_count` | `int`                       | No       | `0`     | Count of holdings.                             |
| `day_change_inr` | `ConfiguredDecimal \| None` | No       | `None`  | Daily valuation change in INR.                 |
| `xirr`           | `float \| None`             | No       | `None`  | Overall money-weighted annualized return.      |
| `period_returns` | `list[PeriodReturn]`        | No       | `[]`    | Trailing window return points.                 |
| `asset_mix`      | `list[AssetMixRow]`         | No       | `[]`    | Breakdown by asset class (Equity, Debt, Cash). |
| `amc_mix`        | `list[AllocationBucket]`    | No       | `[]`    | Breakdown by Asset Management Company.         |
| `category_mix`   | `list[AllocationBucket]`    | No       | `[]`    | Breakdown by SEBI mutual fund category.        |
| `top_holdings`   | `list[Holding]`             | No       | `[]`    | Subset of top holdings by value.               |
| `holdings`       | `list[Holding]`             | No       | `[]`    | Full list of priced holdings.                  |

#### `AssetMixRow`

| Field           | Type                | Required | Description                                     |
| :-------------- | :------------------ | :------- | :---------------------------------------------- |
| `security_type` | `str`               | Yes      | Asset classification (e.g. `'mf'`, `'equity'`). |
| `value_inr`     | `ConfiguredDecimal` | Yes      | Valuation in INR.                               |

#### `AllocationBucket`

| Field       | Type                | Required | Description                |
| :---------- | :------------------ | :------- | :------------------------- |
| `label`     | `str`               | Yes      | AMC name or category name. |
| `value_inr` | `ConfiguredDecimal` | Yes      | Valuation in INR.          |

#### `PeriodReturn`

| Field        | Type            | Required | Description                                       |
| :----------- | :-------------- | :------- | :------------------------------------------------ |
| `period`     | `str`           | Yes      | Evaluation window (e.g. `'1M'`, `'1Y'`, `'ALL'`). |
| `annualized` | `float`         | Yes      | Annualized rate of return.                        |
| `absolute`   | `float \| None` | No       | Absolute percentage return.                       |
| `days`       | `int`           | Yes      | Number of calendar days evaluated.                |

---

### 4. Holding & Security Models

#### `Holding`

Priced holding under an investor.

| Field            | Type                        | Required | Description                  |
| :--------------- | :-------------------------- | :------- | :--------------------------- |
| `security_id`    | `int`                       | Yes      | Identifier of the security.  |
| `name`           | `str`                       | Yes      | Scheme name.                 |
| `security_type`  | `str`                       | Yes      | Security classification.     |
| `symbol`         | `str`                       | No       | Ticker symbol if traded.     |
| `amc`            | `str`                       | No       | AMC company name.            |
| `category`       | `str`                       | No       | Category name.               |
| `units`          | `ConfiguredDecimal`         | Yes      | Units held.                  |
| `value_inr`      | `ConfiguredDecimal \| None` | No       | Market value in INR.         |
| `invested_inr`   | `ConfiguredDecimal \| None` | No       | Invested capital cost basis. |
| `latest_nav`     | `ConfiguredDecimal \| None` | No       | Latest recorded NAV.         |
| `return_pct`     | `float \| None`             | No       | Absolute percentage return.  |
| `xirr`           | `float \| None`             | No       | Annualized return rate.      |
| `day_change_inr` | `ConfiguredDecimal \| None` | No       | Daily value delta in INR.    |
| `day_change_pct` | `float \| None`             | No       | Daily percentage change.     |

#### `SchemeDetail`

Detailed holding report including history and folios.

| Field          | Type                        | Required | Description                            |
| :------------- | :-------------------------- | :------- | :------------------------------------- |
| `security`     | `SchemeRef`                 | Yes      | Scheme reference metadata.             |
| `as_of`        | `ConfiguredDate`            | Yes      | Valuation date.                        |
| `units`        | `ConfiguredDecimal`         | Yes      | Units held.                            |
| `value_inr`    | `ConfiguredDecimal \| None` | No       | Total value.                           |
| `invested_inr` | `ConfiguredDecimal \| None` | No       | Cost basis.                            |
| `folios`       | `list[FolioBalance]`        | No       | List of folio breakdown items.         |
| `nav_history`  | `list[NavPoint]`            | No       | Time-series NAV points.                |
| `transactions` | `list[Transaction]`         | No       | Ledger transactions for this security. |

---

### 5. Transactions & Ledgers

#### `Transaction`

| Field              | Type                        | Required | Description                               |
| :----------------- | :-------------------------- | :------- | :---------------------------------------- |
| `id`               | `int`                       | Yes      | Ledger transaction ID.                    |
| `investor_id`      | `int`                       | Yes      | Investor ID.                              |
| `security_id`      | `int`                       | Yes      | Security ID.                              |
| `date`             | `ConfiguredDate`            | Yes      | Transaction date.                         |
| `transaction_type` | `str`                       | Yes      | Type (e.g. `'purchase'`, `'redemption'`). |
| `units`            | `ConfiguredDecimal`         | Yes      | Quantity transacted.                      |
| `nav_or_price`     | `ConfiguredDecimal`         | Yes      | Executed NAV or price.                    |
| `amount`           | `ConfiguredDecimal \| None` | No       | Total transaction amount.                 |
| `fees`             | `ConfiguredDecimal`         | No       | Incurred fees.                            |
| `stamp_duty`       | `ConfiguredDecimal`         | No       | Stamp duty paid.                          |
| `brokerage`        | `ConfiguredDecimal`         | No       | Brokerage paid.                           |

---

### 6. Valuations & Capital Gains

#### `ValueSeries` and `ValueSeriesPoint`

Reconstructed historical net worth points across intervals.

```python
class ValueSeriesPoint(FoliomanBaseModel):
    date: ConfiguredDate
    value_inr: ConfiguredDecimal
    invested_inr: ConfiguredDecimal
    stale: bool = False
```

#### `CapitalGainsReport` and `CapitalGainRow`

Disposal lots for annual tax calculations:

```python
class CapitalGainRow(FoliomanBaseModel):
    security_id: int | None = None
    name: str
    isin: str = ""
    units: ConfiguredDecimal
    sale_value: ConfiguredDecimal
    cost: ConfiguredDecimal
    gain: ConfiguredDecimal
    term: str  # 'STCG' or 'LTCG'
    acquired_on: ConfiguredDate
    sold_on: ConfiguredDate
    grandfathering_unavailable: bool = False
```
