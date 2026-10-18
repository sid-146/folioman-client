# Database Layer & Centralized Diagnostics (`folioman_client.db`)

This document details the database architecture, connection pooling, schema initialization, ORM data models, and the centralized, actionable database error reporting system implemented in `src/folioman_client/db/`.

---

## 1. Asynchronous Architecture & Engine Lifecycle

`folioman-client` is built on **SQLAlchemy 2.0 Async** and supports both **SQLite** (via `aiosqlite`) and **PostgreSQL** (via `psycopg3`).

```mermaid
flowchart TD
    Config["FoliomanSettings\n(database_url)"] --> Factory["create_folioman_engine()"]
    Factory -->|sqlite+aiosqlite| SQLiteEngine["FoliomanAsyncEngine (SQLite)\nWAL Mode, Foreign Keys = ON"]
    Factory -->|postgresql+psycopg| PGEngine["FoliomanAsyncEngine (PostgreSQL)\nAsyncConnectionPool"]

    SQLiteEngine --> Listeners["SQLAlchemy Engine Event Listeners\nhandle_error -> report_database_error()"]
    PGEngine --> Listeners

    Listeners --> SessionFactory["create_sessionmaker() / get_session_factory()"]
    SessionFactory --> Session["FoliomanAsyncSession (AsyncSession)"]
    Session --> ContextManager["handle_db_errors(session) Context Manager"]
```

### 1.1 Windows `ProactorEventLoop` vs `psycopg3` Caveat
On Windows with Python 3.11+, the default asyncio event loop is `ProactorEventLoop`. However, `psycopg3` async mode requires Windows socket file descriptors supported only by `SelectorEventLoop`. When using PostgreSQL on Windows, `folioman-client` or the host process must initialize asyncio with:
```python
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
If this is omitted, the centralized database error reporting mechanism detects the failure immediately, diagnosing:
```text
Cause : psycopg cannot use ProactorEventLoop in async mode.
Fix   : Use a compatible event loop or correct the async driver configuration:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

---

## 2. Centralized Actionable Error Diagnostics (`db/reporting.py` & `db/errors.py`)

SQLAlchemy and driver exceptions can be verbose and difficult to decipher in complex async architectures. `folioman-client` implements a centralized error analysis and reporting system that intercepts exceptions, inspects application call stacks, redacts sensitive PII, and outputs clear, actionable diagnostic blocks.

### 2.1 Standardized Diagnostic Format
Every database failure outputs a concise diagnostic message to `sys.stderr`:

```text
[DATABASE ERROR] sqlalchemy.exc.IntegrityError

Backend   : SQLite
Operation : INSERT
Query     : INSERT INTO investors (user_id, name, pan_hash) VALUES (?, ?, ?)
Location  : src/folioman_client/services/ledger_service.py:126
Cause     : Unique constraint failed: investors.pan_hash
Fix       : An investor with this PAN or unique identifier already exists.

Original error:
UNIQUE constraint failed: investors.pan_hash
```

### 2.2 Accurate Application Call-Site Resolution
A major challenge in async SQLAlchemy applications is that exceptions are caught deep inside framework code (greenlets, task loops, or connection pool workers). Standard `traceback` parsing often points incorrectly to SQLAlchemy internals (`sqlalchemy/dialects/sqlite/aiosqlite.py`) rather than the application line that issued the query.

`extract_application_location()` solves this:
1. Inspects the active stack frames using `inspect.currentframe()`.
2. Inspects `__traceback__` attached to the exception.
3. If running inside a greenlet, accesses the parent coroutine's stack frame.
4. Filters out internal framework paths:
   - `site-packages/`
   - `sqlalchemy/`
   - `aiosqlite/`
   - `psycopg/`
   - `folioman_client/db/reporting.py`
   - `folioman_client/db/errors.py`
5. Returns the true application call site (e.g. `src/folioman_client/services/ledger_service.py:126`).

### 2.3 Security, Privacy & Secret Redaction
To protect financial confidentiality, the error reporting engine automatically sanitizes all output:
- **Connection URLs**: Passwords and usernames are stripped via `sanitize_url()`.
- **PANs**: Any 10-character Permanent Account Number string matching `[A-Z]{5}[0-9]{4}[A-Z]` is masked to `XXXXXX123D`.
- **Passwords**: Database and PDF passwords in messages or query strings are replaced with `[REDACTED]`.
- **Bound Parameters**: Bound SQL parameters are omitted by default to prevent leaking transaction amounts, folio numbers, or personal details in console logs.

### 2.4 Error De-Duplication
In layered architectures, an exception often bubbles up through several layers (e.g., Session listener $\to$ `handle_db_errors` $\to$ Service method $\to$ CLI command). Without de-duplication, the diagnostic banner would print 3 or 4 times for a single failure.

`report_database_error()` sets an internal flag on the exception instance:
```python
if getattr(exc, "_folioman_db_error_reported", False):
    return info  # Already reported; do not print again
setattr(exc, "_folioman_db_error_reported", True)
```
This guarantees that diagnostic blocks appear **exactly once**.

---

## 3. Schema Migrations & Initialization (`db/migrations.py`)

Database setup is executed via `init_schema(engine)`:
- Invokes `Base.metadata.create_all()` inside an isolated connection block.
- **SQLite Pragmas**:
  - `PRAGMA journal_mode = WAL;` (Write-Ahead Logging for high concurrency).
  - `PRAGMA foreign_keys = ON;` (Enforces referential integrity).
  - `PRAGMA synchronous = NORMAL;` (Optimal balance of durability and write performance).
- **PostgreSQL Settings**:
  - Validates schema visibility and creates required B-Tree indexes.

---

## 4. ORM Model Declarations (`db/models.py`)

`folioman-client` defines 18 SQLAlchemy ORM tables inheriting from a common declarative `Base`:

```mermaid
erDiagram
    Investor ||--o{ Folio : owns
    Investor ||--o{ Transaction : has
    Investor ||--o{ Holding : holds
    Investor ||--o{ InvestorValue : tracked_by
    Investor ||--o{ SecurityIntegrityStatus : audited_by
    Investor ||--o{ AppliedCorporateAction : applies
    Family ||--o{ Investor : includes
    Folio ||--o{ Transaction : contains
    Folio ||--o{ Holding : contains
    Security ||--o{ Transaction : trades
    Security ||--o{ Holding : measures
    Security ||--o{ NAVHistory : priced_by
    Security ||--o{ CorporateActionReference : declares
    AMC ||--o{ Security : issues
```

### 4.1 Core Entity Tables

#### 1. `Investor` (`investors`)
- `id`: Integer primary key.
- `user_id`: String multi-tenant user or advisor identifier.
- `name`: Full legal name.
- `pan_encrypted`: `LargeBinary` Fernet ciphertext of plaintext PAN.
- `pan_hash`: `String(64)` HMAC-SHA256 deterministic digest used for fast indexed lookups without decrypting.
- `family_id`: Nullable foreign key to `Family`.
- `valuation_status`: `"fresh"`, `"stale"`, or `"recomputing"`.

#### 2. `Family` (`families`)
- Groups multiple investors (e.g. spouse, minor children, HUF accounts) for consolidated portfolio summaries.

#### 3. `Folio` (`folios`)
- `investor_id`: Foreign key to `Investor`.
- `number`: Normalized folio / account number.
- `amc_code`: AMFI fund house code.
- `folio_type`: `"mf"` (Mutual Fund) or `"demat"` (Equity Demat Account).

#### 4. `Security` (`securities`)
- `security_type`: `"MF"`, `"EQUITY"`, `"ETF"`, `"BOND"`, `"FD"`.
- `name`: Canonical security name.
- `isin`: 12-character International Securities Identification Number.
- `amfi_code`: AMFI 6-digit mutual fund scheme code.
- `symbol`: Exchange stock ticker (e.g. `RELIANCE`).
- `exchange`: `NSE`, `BSE`, or `NASDAQ`.

#### 5. `Transaction` (`transactions`)
- **Immutable historical ledger record**.
- `investor_id`, `security_id`, `folio_id`.
- `date`: Trade settlement date.
- `transaction_type`: `BUY`, `SELL`, `BONUS`, `TRANSFER_IN`, `TRANSFER_OUT`.
- `units`: `Numeric(18, 4)` share or unit quantity.
- `nav_or_price`: `Numeric(18, 4)` purchase/sale price per unit.
- `amount`: `Numeric(18, 4)` gross trade consideration.
- `fees`, `stamp_duty`: `Numeric(18, 4)` statutory deductions.
- `dedup_key`: `String(64)` SHA-256 idempotency hash.
- `cost_basis_complete`: Boolean flag indicating whether historical cost basis is verified.

#### 6. `Holding` (`holdings`)
- Periodic holding snapshot observed from CAS or eCAS statements. Used for position verification and incomplete history bridging.

#### 7. `NAVHistory` (`nav_history`)
- Historical time series of closing NAVs and prices.
- Composite unique key: `(security_id, date)`.

#### 8. `InvestorValue` (`investor_values`)
- Daily mark-to-market portfolio net worth and cost basis cache.
- Composite unique key: `(investor_id, date)`.

#### 9. `SecurityIntegrityStatus` (`security_integrity_status`)
- Current reconciliation state between ledger transactions and holding snapshots:
  - `status`: `MATCH`, `MISMATCH`, `INCOMPLETE_HISTORY`, `CA_EXPLAINED`, `MANUAL_OVERRIDE`.
  - `ledger_units`, `snapshot_units`, `difference`.

#### 10. `CorporateActionReference` (`corporate_action_references`)
- Repository of historical corporate action events (splits, bonuses, mergers) scraped from exchanges.

#### 11. `AppliedCorporateAction` (`applied_corporate_actions`)
- Junction linking a corporate action reference to an investor's ledger.

#### 12. `ImportJob` & `ImportQuarantine`
- Tracks background statement ingestion jobs and isolates malformed scheme blocks for user review.

#### 13. `PartialBlock`
- Tracks mutual fund schemes with unchained opening units awaiting older statements.

#### 14. `FMVJan2018`
- Reference table storing statutory Jan 31, 2018 grandfathering NAVs and stock prices.
