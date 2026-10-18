# Project Structure & Module Organization

This document provides a comprehensive map of the repository's directory layout, module responsibilities, public interfaces, dependencies, and consumer relationships.

---

## 1. Directory Tree Overview

```text
folioman-client/
├── docs/                        # MkDocs technical documentation
│   ├── execution-flows/         # End-to-end execution path specifications
│   ├── modules/                 # Deep-dive module & function documentation
│   ├── walk through/            # User-oriented asset walkthroughs
│   ├── architecture.md          # System architecture & design principles
│   ├── project-structure.md     # This document
│   ├── setup-and-configuration.md # Environment variables & installation
│   ├── error-handling-and-debugging.md # Error reporting & diagnosis
│   ├── testing.md               # Test suite & verification guide
│   └── CODEBASE_AUDIT.md        # Staff+ architectural audit report
├── examples/                    # Python integration scripts & usage demos
├── src/                         # Source root
│   └── folioman_client/         # Main package root
│       ├── __init__.py          # Public package exports
│       ├── auth.py              # JWT token management & Bearer injection
│       ├── client.py            # FoliomanClient facade & API resources
│       ├── config.py            # FoliomanSettings configuration
│       ├── errors.py            # Domain exception hierarchy
│       ├── models.py            # Public REST / SDK response models
│       ├── types.py             # Type aliases and coercion validators
│       ├── cli/                 # Click CLI subcommands
│       ├── core/                # Pure mathematical models, algorithms & parsers
│       │   ├── models/          # Framework-free domain models
│       │   ├── price_feeds/     # Market data fetchers & web scrapers
│       │   └── tax/             # Indian Capital Gains engine (Schedule 112A)
│       ├── db/                  # Persistence layer (SQLAlchemy 2.0 Async)
│       ├── security/            # Cryptographic PAN protection & key management
│       └── services/            # Application business logic services
├── tests/                       # Pytest test suite (32 test files, 247 tests)
├── .env                         # Environment variables (local credentials)
├── .flake8                      # Flake8 style configuration
├── mkdocs.yml                   # MkDocs site configuration
├── pyproject.toml               # Project metadata & build dependencies
└── uv.lock                      # Deterministic dependency lockfile
```

---

## 2. Root Package (`src/folioman_client/`)

### `__init__.py`
- **Responsibility**: Primary library entry point and namespace export.
- **Key Symbols**: `FoliomanClient`, `FoliomanSettings`, `FoliomanError`, `FoliomanDatabaseError`, `FoliomanNotFoundError`, `__version__`.
- **Dependencies**: `client.py`, `config.py`, `errors.py`, `models.py`.
- **Consumers**: External applications, CLI scripts, tests.

### `client.py`
- **Responsibility**: Unified client interface operating in either **embedded database mode** or **remote REST HTTP mode**.
- **Key Symbols**:
  - `FoliomanClient`: Main client facade.
  - Resource classes: `InvestorsResource`, `FoliosResource`, `TransactionsResource`, `HoldingsResource`, `ValuationsResource`, `CapitalGainsResource`, `ReconcileResource`, `ImportsResource`, `NAVResource`.
- **Dependencies**: `httpx`, `services/`, `models.py`, `errors.py`.
- **Architectural Role**: Acts as an adapter. If `remote_url` is provided, requests dispatch via `httpx.AsyncClient`. Otherwise, it routes directly to embedded local database services (`LedgerService`, `ValuationService`, etc.).

### `config.py`
- **Responsibility**: Environment-backed configuration management via Pydantic Settings.
- **Key Symbols**: `FoliomanSettings`, `get_settings()`, `settings`.
- **Environment Variables**: `FOLIOMAN_DATABASE_URL`, `DB_URL`, `FOLIOMAN_ENCRYPTION_KEY`, `FOLIOMAN_REMOTE_URL`.
- **Consumers**: `db/engine.py`, `security/keys.py`, `client.py`, `cli/main.py`.

### `errors.py`
- **Responsibility**: Central domain exception hierarchy for the client and embedded engine.
- **Key Symbols**:
  - `FoliomanError`: Base exception.
  - `FoliomanAuthError`: Authentication / token refresh failure.
  - `FoliomanNotFoundError`: Resource not found (HTTP 404 / missing entity).
  - `FoliomanParseError`: Statement extraction or parsing failure.
  - `FoliomanPasswordError`: Incorrect PDF password.
  - `FoliomanDatabaseError`: Database connection, timeout, or integrity violation.
  - `DuplicateInvestorError`: Unique constraint violation on PAN.
  - `FernetKeyUnavailable`: Missing PAN encryption key.
  - `FoliomanAPIError`: Remote HTTP 4xx/5xx failure.
- **Consumers**: Entire codebase (services, db, cli, client).

### `models.py`
- **Responsibility**: Pydantic v2 data models representing the public API and response DTOs.
- **Key Symbols**: `InvestorProfile`, `FolioSummary`, `HoldingSummary`, `PortfolioSummary`, `TransactionSummary`, `CapitalGainsReport`.
- **Consumers**: `client.py`, API endpoints, external developers.

---

## 3. Command-Line Interface (`src/folioman_client/cli/`)

The CLI is built with `click` and organized into modular command groups under `folioman_client.cli.main:cli`:

| Module | Command Group | Description & Responsibility |
| :--- | :--- | :--- |
| `main.py` | `folioman` | Root CLI group. Handles global flags (`--database-url`), registers subcommands, and configures Windows event loop policies. |
| `import_cmd.py` | `folioman import` | Commands to ingest CAMS/KFintech CAS and NSDL/CDSL eCAS PDFs (`import cas`). |
| `ledger.py` | `investors`, `folios`, `transactions`, `holdings` | CRUD commands for managing investor profiles, folios, manual transactions, and viewing unit balances. |
| `portfolio.py` | `portfolio` | Portfolio-level commands (`portfolio summary`) to inspect net worth, invested cost, and asset allocation. |
| `valuations.py`| `valuations` | Commands to trigger mark-to-market recomputations and inspect daily valuation histories. |
| `capital_gains.py` | `tax` | Commands to generate Schedule 112A capital gains tax summaries and export ITR CSV files. |
| `nav.py` | `nav` | Market data commands to trigger AMFI / mfapi.in NAV sync and backfill missing pricing gaps. |
| `isin.py` | `isin` | Commands to search and sync the 100k+ master ISIN directory (`isin lookup`, `isin sync`). |
| `reconcile.py` | `reconcile` | Commands to compare CAS closing units against local ledger units and detect transaction gaps. |
| `scheduler.py` | `scheduler` | Background process runner executing recurring NAV refresh and reconciliation jobs via APScheduler. |
| `symbols.py` | `symbols` | Utilities to inspect and map stock ticker symbols to ISIN identifiers. |
| `corporate_actions.py` | `corporate-actions` | Commands to record, inspect, and apply stock splits, bonus issues, and mergers. |

---

## 4. Core Domain Engine (`src/folioman_client/core/`)

The `core/` package contains pure mathematical models, calculation engines, and statement parsers. It is strictly decoupled from the database layer.

### 4.1 Accounting & Financial Math
- **`fifo.py`**: First-In-First-Out (FIFO) lot allocation engine (`FIFOUnits`, `OpenLot`, `ConsumedLot`, `SellDisposal`). Preserves exact total cost basis across corporate actions and allocates stamp duty across sold slices using banker's rounding.
- **`xirr.py`**: Newton-Raphson cash flow solver (`compute_xirr`) with derivative calculation and automatic fallback to a bracketed bisection algorithm in the range `[-0.999999, 100.0]`.
- **`valuation.py`**: Mark-to-market valuation engine calculating current value, unrealized gain, and absolute returns.
- **`trading_calendar.py`**: Business day calculations, holiday calendar awareness, and valuation freshness checking.

### 4.2 Statement Parsers
- **`cas_reader.py`**: PDF routing dispatcher. Inspects document headers to direct files to `parser.py` or `ecas_parser.py`.
- **`parser.py`**: CAMS and KFintech CAS PDF parser. Integrates with `casparser`, executes transaction reversal netting (`_cancel_reversals`), and maps raw statements to `MfCasStatement`.
- **`ecas_parser.py`**: NSDL and CDSL Demat eCAS parser extracting equity trades, ISINs, and demat accounts.
- **`reconciliation.py`**: Pure decision matrix comparing parsed statement closing balances against computed transaction ledger balances.

### 4.3 Corporate Actions
- **`corporate_actions.py`**: Multiplier and ratio math for bonus issues, stock splits, mergers, and demergers (`apply_split`, `apply_bonus`, `apply_merger`). Preserves total acquisition cost (`cost_total`).
- **`corporate_action_detect.py`**: Heuristic gap detector identifying unrecorded stock splits or bonuses when a statement closing balance differs from the transaction sum by an integer ratio.
- **`corporate_action_subject.py`**: Regex parser extracting ratio information from exchange announcement text (e.g. `"Bonus 1:2"`, `"Sub-division from Rs 10 to Rs 2"`).

### 4.4 Indian Taxation (`core/tax/`)
- **`india.py`**: Implements Indian tax rules (`IndiaTaxPolicy`), Section 112A Grandfathering (Jan 31, 2018 FMV deemed cost calculation), Union Budget 2024 cutoff rules (July 23, 2024), and buyback exemptions.
- **`schedule_112a.py`**: Generates the official 14-column ITR Schedule 112A CSV format.
- **`policy.py` & `models.py`**: Tax policy interface and data structures (`Disposal`, `TaxYear`, `Term`).

### 4.5 Market Price Feeds (`core/price_feeds/`)
- **`amfi_bulk.py`**: Downloads and parses daily bulk NAV text files from the Association of Mutual Funds in India (AMFI).
- **`mfapi.py`**: Asynchronous client for `mfapi.in` to backfill historical mutual fund NAV series.
- **`yfinance_feed.py`**: Yahoo Finance client fetching equity, ETF, and index quotes.
- **`nse_bhavcopy.py` & `nse_history.py`**: NSE Bhavcopy archive parser for official closing stock prices.
- **`casparser_fmv.py`**: Static database lookup for January 31, 2018 grandfathering FMV prices.

---

## 5. Persistence Layer (`src/folioman_client/db/`)

The persistence layer manages relational storage using SQLAlchemy 2.0 Asyncio:

- **`engine.py`**:
  - `create_folioman_engine`: Configures SQLite (WAL mode, `synchronous=NORMAL`, `busy_timeout=5000`, foreign keys enabled) or PostgreSQL (connection pooling, pre-ping checks). Sanitizes credentials in error messages.
  - `FoliomanAsyncEngine` & `FoliomanAsyncConnection`: Intercepts connection initialization failures and pool checkout timeouts.
  - `FoliomanAsyncSession`: Overrides `execute`, `commit`, and `flush` to automatically trigger rollbacks and invoke centralized error reporting.
  - `create_sessionmaker`: Factory creating async sessions bound to `FoliomanAsyncSession`.
- **`reporting.py`**:
  - `DatabaseErrorInfo`: Structured diagnostic model capturing exception type, backend, operation, query, location, cause, fix, and original error.
  - `extract_application_location`: Accurately pinpoints the application calling line (`file:line`) by inspecting tracebacks and parent greenlet coroutine frames while filtering internal libraries.
  - `report_database_error`: Emits concise diagnostic blocks to `sys.stderr` and attaches de-duplication markers.
  - Sanitization utilities: `sanitize_url`, `sanitize_query`, `sanitize_message`, `mask_pan`.
- **`errors.py`**:
  - `handle_db_errors`: Async context manager wrapping database calls, rolling back active sessions, reporting errors to console, and re-raising translated domain exceptions with full traceback preservation (`from exc`).
  - `translate_integrity_error`: Translates raw database constraint violations into domain errors (`DuplicateInvestorError`, `FoliomanDatabaseError`).
- **`migrations.py`**:
  - `init_schema`: Idempotently creates all database tables and verifies schema versioning (`SchemaVersion`).
  - `get_schema_version`: Checks the current database migration level.
- **`models.py`**:
  - 18 SQLAlchemy declarative ORM models mapping securities, investors, folios, transactions, holdings, corporate actions, NAV history, and audit jobs.

---

## 6. Security Subsystem (`src/folioman_client/security/`)

Dedicated to protecting sensitive financial identifiers and Personal Identifiable Information (PII):

- **`pan.py`**:
  - `normalize_pan`: Validates and upper-cases Permanent Account Numbers.
  - `mask_pan`: Masks PANs for display and logging (e.g. `XXXXXX234F`).
  - `encrypt_pan` / `decrypt_pan`: Symmetrically encrypts PANs using Fernet (AES-128-CBC with HMAC-SHA256).
  - `pan_hash`: Computes keyed HMAC-SHA256 digests over normalized PANs for deterministic database indexing without storing plaintext.
- **`keys.py`**:
  - `resolve_fernet_key`: Resolves the 32-byte base64 encryption key in order of priority:
    1. Environment variable: `FOLIOMAN_ENCRYPTION_KEY`.
    2. OS Keyring: Service `folioman-client`, username `encryption_key`.
    3. Filesystem storage: `~/.folioman/key`.
    4. Auto-generates a secure key if none exists.

---

## 7. Business Services Layer (`src/folioman_client/services/`)

The services layer orchestrates interactions between the database, market feeds, and core math engines:

| Service Module | Class Name | Responsibility |
| :--- | :--- | :--- |
| `ledger_service.py` | `LedgerService` | Investor profile management, folio tracking, manual transactions, and balance aggregation. |
| `import_service.py` | `ImportService` | CAS PDF parsing, deduplication hash verification, quarantine handling, and batch database ingestion. |
| `valuation_service.py`| `ValuationService` | Mark-to-market portfolio net worth valuation, positions aggregation, daily historical valuations, and XIRR calculation. |
| `capital_gains_service.py` | `CapitalGainsService` | FIFO lot disposal matching, Schedule 112A capital gains computation, and ITR CSV export. |
| `nav_service.py` | `NAVService` | Daily NAV updates from AMFI, historical gap backfilling via mfapi.in, and stale valuation cache invalidation. |
| `corporate_action_service.py` | `CorporateActionService` | Persistence, validation, and retrieval of stock splits, bonuses, and mergers. |
| `reconciliation_service.py` | `ReconciliationService` | Statement vs ledger unit reconciliation and mismatch reporting. |
| `isin_service.py` | `ISINService` | Master ISIN dictionary lookups, AMFI code mappings, and offline database synchronization. |
| `equity_symbol_service.py` | `EquitySymbolService` | Stock ticker symbol resolution to ISINs. |
| `scheduler.py` | `SchedulerService` | APScheduler background worker executing automated NAV updates and reconciliation jobs. |
| `projected_ledger.py` | `projected_transactions` | Generator replaying corporate actions over immutable database transactions on-the-fly. |
| `mappers.py` | *(functions)* | Lossless converters translating between DB ORM models and core domain models. |
