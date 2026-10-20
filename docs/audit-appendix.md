# Appendix: Comprehensive Files Inspected Manifest

This appendix provides the complete, structured inventory of all source files and test suites inspected during the architectural audit of `folioman-client`. It details the role, key exported symbols, and line counts for each module across all subsystems.

---

## 1. Source Modules by Subsystem (88 Files in `src/folioman_client`)

### Package Core & Public Facade (7 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/__init__.py` | 141 | Top-level package initialization and public symbol exports. | — |
| `src/folioman_client/auth.py` | 244 | JWT authentication lifecycle, token refresh buffer, and bearer injection. | `JWTAuthManager` |
| `src/folioman_client/client.py` | 1090 | Unified FoliomanClient facade dispatching to embedded services or remote REST endpoints. | `_BaseResource`, `InvestorsResource`, +13 classes |
| `src/folioman_client/config.py` | 112 | FoliomanSettings configuration via pydantic-settings and environment variable resolution. | `FoliomanSettings` |
| `src/folioman_client/errors.py` | 100 | Domain exception hierarchy and HTTP status code mappings. | `FoliomanError`, `FoliomanAuthError`, +8 classes |
| `src/folioman_client/models.py` | 806 | Public API response models and DTOs (PortfolioSummary, Holding, Transaction, etc.). | `FoliomanBaseModel`, `TokenPair`, +38 classes |
| `src/folioman_client/types.py` | 33 | Custom serialization types, decimal coercers, and ISO date formatters. | — |

### Command Line Interface (CLI) (13 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/cli/__init__.py` | 5 | CLI subpackage initialization. | — |
| `src/folioman_client/cli/capital_gains.py` | 132 | CLI subcommands for Schedule 112A tax reports and capital gains summaries. | `capital_gains_group()`, `list_cmd()`, +1 funcs |
| `src/folioman_client/cli/corporate_actions.py` | 123 | CLI subcommands to sync, apply, and audit stock splits and bonus issues. | `corporate_actions_group()`, `refresh_cmd()`, +2 funcs |
| `src/folioman_client/cli/import_cmd.py` | 109 | CLI subcommands to ingest CAS and eCAS PDF statements. | `import_group()`, `import_cas_cmd()` |
| `src/folioman_client/cli/isin.py` | 138 | CLI subcommands to seed, sync, and inspect national ISIN master catalog. | `isin_group()`, `status_cmd()`, +4 funcs |
| `src/folioman_client/cli/ledger.py` | 216 | CLI subcommands for investor CRUD, folio management, and manual transactions. | `investors_group()`, `list_investors_cmd()`, +8 funcs |
| `src/folioman_client/cli/main.py` | 83 | Root Click CLI group ('folioman') and global option handling. | `FoliomanCLI` |
| `src/folioman_client/cli/nav.py` | 111 | CLI subcommands to refresh live NAVs and trigger historical backfills. | `nav_group()`, `refresh_cmd()`, +2 funcs |
| `src/folioman_client/cli/portfolio.py` | 80 | CLI subcommands to inspect portfolio net worth and holdings. | `portfolio_group()`, `summary_cmd()` |
| `src/folioman_client/cli/reconcile.py` | 85 | CLI subcommands to verify ledger vs holding snapshot consistency. | `reconcile_group()`, `reconcile_all_cmd()`, +2 funcs |
| `src/folioman_client/cli/scheduler.py` | 37 | CLI subcommands to launch the background APScheduler daemon. | `scheduler_group()`, `run_cmd()` |
| `src/folioman_client/cli/symbols.py` | 74 | CLI subcommands to resolve trading tickers (NSE/BSE) from ISINs. | `symbols_group()`, `resolve_cmd()` |
| `src/folioman_client/cli/valuations.py` | 126 | CLI subcommands to trigger valuation recomputation and inspect status. | `valuations_group()`, `status_cmd()`, +2 funcs |

### Core Math & Parsers (16 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/core/__init__.py` | 3 | Core calculation engines subpackage initialization. | — |
| `src/folioman_client/core/_dates.py` | 29 | Flexible date parsing helpers for diverse Indian financial statement formats. | `parse_loose_date()` |
| `src/folioman_client/core/cas_reader.py` | 70 | Low-level CAS PDF extraction and decryption via PDFium / casparser. | `ParsedCas` |
| `src/folioman_client/core/corporate_action_detect.py` | 293 | Automatic detection of corporate actions from holding mismatches. | `CachedCorporateAction`, `ReplayStep`, +1 classes |
| `src/folioman_client/core/corporate_action_subject.py` | 177 | Parser for exchange corporate action announcement subjects. | `CorpActionType`, `ParsedCorporateAction` |
| `src/folioman_client/core/corporate_actions.py` | 670 | Corporate action multiplier calculation (split/bonus ratio math). | `CorporateActionApplyEvent` |
| `src/folioman_client/core/dividend_attribution.py` | 98 | Implements dividend attribution components. | `DividendScheduleRow`, `DividendAttributionRow` |
| `src/folioman_client/core/ecas_parser.py` | 238 | NSDL / CDSL eCAS depository statement parser. | `_depository_from_file_type()`, `_map_equity_holding()`, +7 funcs |
| `src/folioman_client/core/fifo.py` | 491 | Strict First-In-First-Out (FIFO) lot allocation engine. | `InsufficientUnitsError`, `OpenLot`, +3 classes |
| `src/folioman_client/core/identity_remap.py` | 32 | Implements identity remap components. | `_same_security()`, `remap_transaction_identities()` |
| `src/folioman_client/core/opening_lot.py` | 22 | Implements opening lot components. | `OpeningLotKind` |
| `src/folioman_client/core/parser.py` | 593 | Reversal netting, fee extraction, and CAS line item normalization. | `CASParseError`, `CASPasswordError`, +1 classes |
| `src/folioman_client/core/reconciliation.py` | 117 | Numerical tolerance and discrepancy classification helpers. | `IntegrityStatus`, `ReconciliationResult` |
| `src/folioman_client/core/trading_calendar.py` | 49 | Indian trading day calendar, holiday resolution, and business day arithmetic. | `last_trading_day()`, `trading_days_between()`, +2 funcs |
| `src/folioman_client/core/valuation.py` | 175 | Core valuation aggregation functions. | `HoldingValuation`, `PortfolioValuation` |
| `src/folioman_client/core/xirr.py` | 128 | Hybrid Newton-Raphson solver with bisection fallback for annualized XIRR. | `CashFlow` |

### Core Domain Models (12 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/core/models/__init__.py` | 44 | Implements   init   components. | — |
| `src/folioman_client/core/models/base.py` | 15 | Implements base components. | `DomainModel` |
| `src/folioman_client/core/models/cas.py` | 143 | Implements cas components. | `Depository`, `CasInvestorIdentity`, +6 classes |
| `src/folioman_client/core/models/corporate_action.py` | 21 | Implements corporate action components. | `CorporateActionEvent` |
| `src/folioman_client/core/models/currency_fields.py` | 25 | Implements currency fields components. | `normalize_currency()`, `validate_currency()` |
| `src/folioman_client/core/models/decimal_fields.py` | 51 | Implements decimal fields components. | `coerce_decimal()`, `coerce_optional_decimal()` |
| `src/folioman_client/core/models/holding.py` | 57 | Implements holding components. | `HoldingSource`, `Holding` |
| `src/folioman_client/core/models/investor.py` | 81 | Implements investor components. | `FolioType`, `Folio`, +1 classes |
| `src/folioman_client/core/models/nav.py` | 55 | Implements nav components. | `NAVPoint`, `NAVHistory` |
| `src/folioman_client/core/models/quote.py` | 27 | Implements quote components. | `Quote` |
| `src/folioman_client/core/models/security.py` | 132 | Implements security components. | `SecurityType`, `Security` |
| `src/folioman_client/core/models/transaction.py` | 123 | Implements transaction components. | `TransactionType`, `TransactionSource`, +1 classes |

### Market Price Feeds (12 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/core/price_feeds/__init__.py` | 1 | Implements   init   components. | — |
| `src/folioman_client/core/price_feeds/amfi_bulk.py` | 163 | Implements amfi bulk components. | `shared_client()`, `_is_transient()`, +5 funcs |
| `src/folioman_client/core/price_feeds/captnemo.py` | 177 | Implements captnemo components. | `shared_client()`, `_is_transient()`, +4 funcs |
| `src/folioman_client/core/price_feeds/casparser_fmv.py` | 34 | Implements casparser fmv components. | `fmv_lookup()` |
| `src/folioman_client/core/price_feeds/coingecko.py` | 88 | Implements coingecko components. | `fetch_quote()`, `fetch_quotes()`, +1 funcs |
| `src/folioman_client/core/price_feeds/corporate_actions_fetch.py` | 473 | Implements corporate actions fetch components. | `CorporateActionFetchError`, `CorporateActionThrottled` |
| `src/folioman_client/core/price_feeds/errors.py` | 11 | Implements errors components. | `NAVFetchError`, `PriceFetchError` |
| `src/folioman_client/core/price_feeds/mfapi.py` | 159 | Implements mfapi components. | `shared_client()`, `_is_transient()`, +4 funcs |
| `src/folioman_client/core/price_feeds/nse_bhavcopy.py` | 139 | Implements nse bhavcopy components. | `warmed_client()`, `_udiff_url()`, +8 funcs |
| `src/folioman_client/core/price_feeds/nse_bse_client.py` | 230 | Implements nse bse client components. | `ResponseTooLargeError`, `ExchangeClient` |
| `src/folioman_client/core/price_feeds/nse_history.py` | 164 | Implements nse history components. | `warmed_client()`, `_windows()`, +2 funcs |
| `src/folioman_client/core/price_feeds/yfinance_feed.py` | 214 | Implements yfinance feed components. | `shared_client()`, `yahoo_symbol()`, +5 funcs |

### Tax Engine (Schedule 112A) (6 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/core/tax/__init__.py` | 23 | Implements   init   components. | — |
| `src/folioman_client/core/tax/india.py` | 164 | Implements india components. | `IndiaTaxPolicy` |
| `src/folioman_client/core/tax/ltcg_stcg.py` | 96 | Implements ltcg stcg components. | `disposal_from_lot()`, `disposals_from_sells()`, +2 funcs |
| `src/folioman_client/core/tax/models.py` | 56 | Implements models components. | `Term`, `TaxYear`, +2 classes |
| `src/folioman_client/core/tax/policy.py` | 46 | Implements policy components. | `TaxPolicy` |
| `src/folioman_client/core/tax/schedule_112a.py` | 221 | Implements schedule 112a components. | `Schedule112ARow` |

### Database & Persistence Layer (6 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/db/__init__.py` | 82 | Database persistence subpackage initialization. | — |
| `src/folioman_client/db/engine.py` | 221 | FoliomanAsyncEngine creation, SQLite WAL mode pragmas, and sessionmaker factories. | `FoliomanAsyncConnection`, `FoliomanAsyncEngine`, +1 classes |
| `src/folioman_client/db/errors.py` | 217 | Implements errors components. | `_clean_orig_message()`, `_safe_rollback()`, +3 funcs |
| `src/folioman_client/db/migrations.py` | 79 | init_schema() DDL initialization and schema version tracking. | `init_schema()`, `get_schema_version()` |
| `src/folioman_client/db/models.py` | 745 | 18 SQLAlchemy 2.0 ORM DeclarativeBase table models. | `Base`, `TimeStampedMixin`, +21 classes |
| `src/folioman_client/db/reporting.py` | 671 | Implements reporting components. | `DatabaseErrorInfo` |

### Security & Cryptography (3 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/security/__init__.py` | 21 | Security and cryptography subpackage initialization. | — |
| `src/folioman_client/security/keys.py` | 80 | Fernet master encryption key resolution (Env -> Keyring -> File). | `_generate_key_file()`, `resolve_fernet_key()`, +2 funcs |
| `src/folioman_client/security/pan.py` | 55 | PAN normalization, masking (XXXXXX123F), Fernet encryption, and HMAC-SHA256 hashing. | `normalize_pan()`, `mask_pan()`, +3 funcs |

### Application Business Services (13 files)

| File | Lines | Primary Responsibility | Key Classes / Functions |
| :--- | :---: | :--- | :--- |
| `src/folioman_client/services/__init__.py` | 25 | Application services package initialization. | — |
| `src/folioman_client/services/capital_gains_service.py` | 373 | Indian capital gains tax calculations (Sec 111A, 112, 112A, 50AA) and ITR export. | `CapitalGainsService` |
| `src/folioman_client/services/corporate_action_service.py` | 345 | Corporate action reference persistence and on-the-fly multiplier applications. | `CorporateActionService` |
| `src/folioman_client/services/equity_symbol_service.py` | 162 | Stock ticker resolution and exchange calendar management. | `EquitySymbolService` |
| `src/folioman_client/services/import_service.py` | 791 | CAS statement parsing, PDF decryption, reversal netting, and savepoint ingestion. | `CASImportService` |
| `src/folioman_client/services/isin_service.py` | 415 | 100k+ master ISIN dictionary and Jan 31, 2018 grandfathering NAV lookup. | `ISINService` |
| `src/folioman_client/services/ledger_service.py` | 564 | Atomic database operations for investors, folios, and manual ledger transactions. | `LedgerService` |
| `src/folioman_client/services/mappers.py` | 107 | Data transformation adapters between API DTOs, Core Domain models, and ORM tables. | `to_core_security()`, `to_core_transaction()`, +1 funcs |
| `src/folioman_client/services/nav_service.py` | 683 | Multi-source market NAV synchronization (AMFI, mfapi, Yahoo, NSE). | `_FeedClients`, `NAVService` |
| `src/folioman_client/services/projected_ledger.py` | 253 | Virtual dynamic ledger replay interleaving historical transactions with corporate actions. | `security_key()`, `demerger_reductions()`, +4 funcs |
| `src/folioman_client/services/reconciliation_service.py` | 616 | Ledger vs snapshot holding reconciliation and corporate action discrepancy detection. | `ReconciliationService` |
| `src/folioman_client/services/scheduler.py` | 161 | APScheduler background daily job orchestration. | `FoliomanScheduler` |
| `src/folioman_client/services/valuation_service.py` | 1981 | Point-in-time valuations, asset mix breakdowns, and annualized XIRR calculations. | `ValuationService` |

---

## 2. Test Suites Inspected (31 Files in `tests/`)

| Test File | Test Functions | Scope & Verification Focus |
| :--- | :---: | :--- |
| `tests/test_auth.py` | 12 | Validates Auth functionality and edge cases. |
| `tests/test_capital_gains_service.py` | 12 | Validates Capital gains service functionality and edge cases. |
| `tests/test_cas_reader.py` | 7 | Validates Cas reader functionality and edge cases. |
| `tests/test_cli_import.py` | 2 | Validates Cli import functionality and edge cases. |
| `tests/test_cli_isin.py` | 1 | Validates Cli isin functionality and edge cases. |
| `tests/test_cli_nav.py` | 4 | Validates Cli nav functionality and edge cases. |
| `tests/test_cli_phase5.py` | 9 | Validates Cli phase5 functionality and edge cases. |
| `tests/test_cli_phase6.py` | 10 | Validates Cli phase6 functionality and edge cases. |
| `tests/test_client.py` | 22 | Validates Client functionality and edge cases. |
| `tests/test_client_embedded.py` | 14 | Validates Client embedded functionality and edge cases. |
| `tests/test_core_cas_parser.py` | 5 | Validates Core cas parser functionality and edge cases. |
| `tests/test_corporate_action_detect.py` | 22 | Validates Corporate action detect functionality and edge cases. |
| `tests/test_corporate_action_service.py` | 6 | Validates Corporate action service functionality and edge cases. |
| `tests/test_database_error_reporting.py` | 30 | Validates Database error reporting functionality and edge cases. |
| `tests/test_db_errors.py` | 6 | Validates Db errors functionality and edge cases. |
| `tests/test_ecas_parser.py` | 13 | Validates Ecas parser functionality and edge cases. |
| `tests/test_engine.py` | 9 | Validates Engine functionality and edge cases. |
| `tests/test_equity_symbol_service.py` | 2 | Validates Equity symbol service functionality and edge cases. |
| `tests/test_import_service.py` | 16 | Validates Import service functionality and edge cases. |
| `tests/test_isin_service.py` | 16 | Validates Isin service functionality and edge cases. |
| `tests/test_ledger_service.py` | 14 | Validates Ledger service functionality and edge cases. |
| `tests/test_migrations.py` | 8 | Validates Migrations functionality and edge cases. |
| `tests/test_models.py` | 10 | Validates Models functionality and edge cases. |
| `tests/test_nav_service.py` | 8 | Validates Nav service functionality and edge cases. |
| `tests/test_parser.py` | 29 | Validates Parser functionality and edge cases. |
| `tests/test_price_feeds.py` | 8 | Validates Price feeds functionality and edge cases. |
| `tests/test_reconciliation.py` | 10 | Validates Reconciliation functionality and edge cases. |
| `tests/test_scheduler.py` | 6 | Validates Scheduler functionality and edge cases. |
| `tests/test_security_pan.py` | 10 | Validates Security pan functionality and edge cases. |
| `tests/test_trading_calendar.py` | 5 | Validates Trading calendar functionality and edge cases. |
| `tests/test_valuation_service.py` | 12 | Validates Valuation service functionality and edge cases. |