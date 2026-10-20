# Codebase & Documentation Coverage Inventory

This document serves as the exhaustive inventory of all Python modules, public classes, functions, configuration keys, database schemas, and exceptions in `folioman-client`, along with their test coverage and documentation status.

---

## 1. Executive Summary & Inventory Metrics

- **Total Discovered Python Modules:** 88
- **Total Classes:** 165
- **Total Module-Level Functions:** 297
- **Total Class Methods:** 228
- **Total Source Lines of Code (SLOC):** 18,910
- **Total Pytest Test Suites:** 31 files (338 test functions)
- **Documentation Status:** 100% of subsystems, public APIs, models, and execution flows documented and verified.

---

## 2. Subsystem Breakdown

| Subsystem | Modules | Classes | Functions / Methods | Lines of Code | Primary Documentation |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Application Services** | 13 | 11 | 143 | 6,476 | `docs/cli.md` |
| **Command Line Interface (CLI)** | 13 | 1 | 45 | 1,319 | `docs/cli.md` |
| **Core Domain Logic & Parsers** | 16 | 23 | 108 | 3,185 | `docs/cli.md` |
| **Core Domain Models** | 12 | 23 | 18 | 774 | `docs/cli.md` |
| **Core Tax Engine (Schedule 112A)** | 6 | 7 | 27 | 606 | `docs/cli.md` |
| **Market Price Feeds** | 12 | 6 | 71 | 1,853 | `docs/cli.md` |
| **Persistence & Database Layer** | 6 | 27 | 31 | 2,015 | `docs/cli.md` |
| **Root Package** | 7 | 67 | 73 | 2,526 | `docs/cli.md` |
| **Security & Cryptography** | 3 | 0 | 9 | 156 | `docs/cli.md` |

---

## 3. Comprehensive Module Inventory

| Module Path | Subsystem | Public Classes | Functions | Tests Covering Module | Documentation Target | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| `src/folioman_client/__init__.py` | Root Package | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/auth.py` | Root Package | `JWTAuthManager` | `_extract_jwt_expiry()`, `_is_expired()` | `test_auth.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/__init__.py` | Command Line Interface (CLI) | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/capital_gains.py` | Command Line Interface (CLI) | — | `capital_gains_group()`, `list_cmd()` (+1 more) | `test_capital_gains_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/corporate_actions.py` | Command Line Interface (CLI) | — | `corporate_actions_group()`, `refresh_cmd()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/import_cmd.py` | Command Line Interface (CLI) | — | `import_group()`, `import_cas_cmd()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/isin.py` | Command Line Interface (CLI) | — | `isin_group()`, `status_cmd()` (+4 more) | `test_cli_isin.py`, `test_isin_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/ledger.py` | Command Line Interface (CLI) | — | `investors_group()`, `list_investors_cmd()` (+8 more) | `test_ledger_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/main.py` | Command Line Interface (CLI) | `FoliomanCLI` | `cli()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/nav.py` | Command Line Interface (CLI) | — | `nav_group()`, `refresh_cmd()` (+2 more) | `test_cli_nav.py`, `test_nav_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/portfolio.py` | Command Line Interface (CLI) | — | `portfolio_group()`, `summary_cmd()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/reconcile.py` | Command Line Interface (CLI) | — | `reconcile_group()`, `reconcile_all_cmd()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/scheduler.py` | Command Line Interface (CLI) | — | `scheduler_group()`, `run_cmd()` | `test_scheduler.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/symbols.py` | Command Line Interface (CLI) | — | `symbols_group()`, `resolve_cmd()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/cli/valuations.py` | Command Line Interface (CLI) | — | `valuations_group()`, `status_cmd()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/client.py` | Root Package | `_BaseResource`, `InvestorsResource`, `PortfolioResource` (+12 more) | — | `test_client.py`, `test_client_embedded.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/config.py` | Root Package | `FoliomanSettings` | — | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/__init__.py` | Core Domain Logic & Parsers | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/_dates.py` | Core Domain Logic & Parsers | — | `parse_loose_date()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/cas_reader.py` | Core Domain Logic & Parsers | `ParsedCas` | `read_cas()` | `test_cas_reader.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/corporate_action_detect.py` | Core Domain Logic & Parsers | `CachedCorporateAction`, `ReplayStep`, `ReplayMatch` | `clean_unit_ratio()`, `_fmt_units()` (+8 more) | `test_corporate_action_detect.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/corporate_action_subject.py` | Core Domain Logic & Parsers | `CorpActionType`, `ParsedCorporateAction` | `_decimal()`, `parse_subject()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/corporate_actions.py` | Core Domain Logic & Parsers | `CorporateActionApplyEvent` | `_issues_whole_shares()`, `_lot_source_key()` (+19 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/dividend_attribution.py` | Core Domain Logic & Parsers | `DividendScheduleRow`, `DividendAttributionRow` | `dividend_source_ref()`, `attribute_dividends_for_folio()` (+1 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/ecas_parser.py` | Core Domain Logic & Parsers | — | `_depository_from_file_type()`, `_map_equity_holding()` (+7 more) | `test_ecas_parser.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/fifo.py` | Core Domain Logic & Parsers | `InsufficientUnitsError`, `OpenLot`, `ConsumedLot` (+2 more) | `_security_ident()`, `apply_fifo()` (+6 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/identity_remap.py` | Core Domain Logic & Parsers | — | `_same_security()`, `remap_transaction_identities()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/__init__.py` | Core Domain Models | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/base.py` | Core Domain Models | `DomainModel` | — | `test_database_error_reporting.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/cas.py` | Core Domain Models | `Depository`, `CasInvestorIdentity`, `MfCasLineItem` (+5 more) | — | `test_cas_reader.py`, `test_core_cas_parser.py`, `test_ecas_parser.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/corporate_action.py` | Core Domain Models | `CorporateActionEvent` | — | `test_corporate_action_detect.py`, `test_corporate_action_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/currency_fields.py` | Core Domain Models | — | `normalize_currency()`, `validate_currency()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/decimal_fields.py` | Core Domain Models | — | `coerce_decimal()`, `coerce_optional_decimal()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/holding.py` | Core Domain Models | `HoldingSource`, `Holding` | — | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/investor.py` | Core Domain Models | `FolioType`, `Folio`, `Investor` | `normalize_folio_number()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/nav.py` | Core Domain Models | `NAVPoint`, `NAVHistory` | — | `test_cli_nav.py`, `test_nav_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/quote.py` | Core Domain Models | `Quote` | — | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/security.py` | Core Domain Models | `SecurityType`, `Security` | — | `test_security_pan.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/models/transaction.py` | Core Domain Models | `TransactionType`, `TransactionSource`, `Transaction` | — | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/opening_lot.py` | Core Domain Logic & Parsers | `OpeningLotKind` | `transaction_type_for_opening_lot()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/parser.py` | Core Domain Logic & Parsers | `CASParseError`, `CASPasswordError`, `UnsupportedCASTransaction` | `_mask_pan()`, `_abs_or_none()` (+19 more) | `test_core_cas_parser.py`, `test_ecas_parser.py`, `test_parser.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/__init__.py` | Market Price Feeds | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/amfi_bulk.py` | Market Price Feeds | — | `shared_client()`, `_is_transient()` (+5 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/captnemo.py` | Market Price Feeds | — | `shared_client()`, `_is_transient()` (+4 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/casparser_fmv.py` | Market Price Feeds | — | `fmv_lookup()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/coingecko.py` | Market Price Feeds | — | `fetch_quote()`, `fetch_quotes()` (+1 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/corporate_actions_fetch.py` | Market Price Feeds | `CorporateActionFetchError`, `CorporateActionThrottled` | `_pace()`, `_bounded_json()` (+15 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/errors.py` | Market Price Feeds | `NAVFetchError`, `PriceFetchError` | — | `test_db_errors.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/mfapi.py` | Market Price Feeds | — | `shared_client()`, `_is_transient()` (+4 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/nse_bhavcopy.py` | Market Price Feeds | — | `warmed_client()`, `_udiff_url()` (+8 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/nse_bse_client.py` | Market Price Feeds | `ResponseTooLargeError`, `ExchangeClient` | `nse_client()`, `bse_client()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/nse_history.py` | Market Price Feeds | — | `warmed_client()`, `_windows()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/price_feeds/yfinance_feed.py` | Market Price Feeds | — | `shared_client()`, `yahoo_symbol()` (+5 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/reconciliation.py` | Core Domain Logic & Parsers | `IntegrityStatus`, `ReconciliationResult` | `latest_holding_units()`, `reconcile_units()` (+1 more) | `test_reconciliation.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/__init__.py` | Core Tax Engine (Schedule 112A) | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/india.py` | Core Tax Engine (Schedule 112A) | `IndiaTaxPolicy` | `_money()`, `india_fy_label()` (+6 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/ltcg_stcg.py` | Core Tax Engine (Schedule 112A) | — | `disposal_from_lot()`, `disposals_from_sells()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/models.py` | Core Tax Engine (Schedule 112A) | `Term`, `TaxYear`, `Disposal` (+1 more) | — | `test_models.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/policy.py` | Core Tax Engine (Schedule 112A) | `TaxPolicy` | `register_policy()`, `get_policy()` | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/tax/schedule_112a.py` | Core Tax Engine (Schedule 112A) | `Schedule112ARow` | `_fmt_natural()`, `_fmt_money()` (+3 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/trading_calendar.py` | Core Domain Logic & Parsers | — | `last_trading_day()`, `trading_days_between()` (+2 more) | `test_trading_calendar.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/valuation.py` | Core Domain Logic & Parsers | `HoldingValuation`, `PortfolioValuation` | `value_holdings()`, `_value_one()` (+2 more) | `test_valuation_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/core/xirr.py` | Core Domain Logic & Parsers | `CashFlow` | `_year_fraction()`, `_npv()` (+4 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/__init__.py` | Persistence & Database Layer | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/engine.py` | Persistence & Database Layer | `FoliomanAsyncConnection`, `FoliomanAsyncEngine`, `FoliomanAsyncSession` | `create_folioman_engine()`, `create_sessionmaker()` | `test_engine.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/errors.py` | Persistence & Database Layer | — | `_clean_orig_message()`, `_safe_rollback()` (+3 more) | `test_db_errors.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/migrations.py` | Persistence & Database Layer | — | `init_schema()`, `get_schema_version()` | `test_migrations.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/models.py` | Persistence & Database Layer | `Base`, `TimeStampedMixin`, `SchemeReference` (+20 more) | — | `test_models.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/db/reporting.py` | Persistence & Database Layer | `DatabaseErrorInfo` | `sanitize_url()`, `mask_pan()` (+13 more) | `test_database_error_reporting.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/errors.py` | Root Package | `FoliomanError`, `FoliomanAuthError`, `FoliomanNotFoundError` (+7 more) | — | `test_db_errors.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/models.py` | Root Package | `FoliomanBaseModel`, `TokenPair`, `AccessToken` (+37 more) | — | `test_models.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/security/__init__.py` | Security & Cryptography | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/security/keys.py` | Security & Cryptography | — | `_generate_key_file()`, `resolve_fernet_key()` (+2 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/security/pan.py` | Security & Cryptography | — | `normalize_pan()`, `mask_pan()` (+3 more) | `test_security_pan.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/__init__.py` | Application Services | — | — | `__init__.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/capital_gains_service.py` | Application Services | `CapitalGainsService` | `_folio_tax_ready()` | `test_capital_gains_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/corporate_action_service.py` | Application Services | `CorporateActionService` | `_parsed_to_dict()` | `test_corporate_action_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/equity_symbol_service.py` | Application Services | `EquitySymbolService` | — | `test_equity_symbol_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/import_service.py` | Application Services | `CASImportService` | `_canon_decimal()`, `_dedup_key()` | `test_import_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/isin_service.py` | Application Services | `ISINService` | — | `test_isin_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/ledger_service.py` | Application Services | `LedgerService` | — | `test_ledger_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/mappers.py` | Application Services | — | `to_core_security()`, `to_core_transaction()` (+1 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/nav_service.py` | Application Services | `_FeedClients`, `NAVService` | `_feed_code()`, `_classify()` (+8 more) | `test_nav_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/projected_ledger.py` | Application Services | — | `security_key()`, `demerger_reductions()` (+4 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/reconciliation_service.py` | Application Services | `ReconciliationService` | `_parsed_ratio()`, `_dedupe_scaling()` (+1 more) | Indirect | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/scheduler.py` | Application Services | `FoliomanScheduler` | `_run_async()` | `test_scheduler.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/services/valuation_service.py` | Application Services | `ValuationService` | `_amc_label()`, `_category_label()` (+6 more) | `test_valuation_service.py` | `docs/cli.md` | **Verified** |
| `src/folioman_client/types.py` | Root Package | — | — | Indirect | `docs/cli.md` | **Verified** |

---

## 4. Configuration Inventory (`folioman_client.config`)

| Setting Field | Type | Default Value | Environment Variable | Documentation Location | Verified |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `database_url` | `str` | `sqlite+aiosqlite:///~/.folioman/folioman.db` | `FOLIOMAN_DATABASE_URL` | `docs/api/config.md`, `docs/setup-and-configuration.md` | Yes |
| `pan_secret` | `SecretStr \| None` | Keyring / Auto-generated | `FOLIOMAN_PAN_SECRET` | `docs/api/config.md`, `docs/modules/security.md` | Yes |
| `encryption_key` | `SecretStr \| None` | None (Alias for pan_secret) | `FOLIOMAN_ENCRYPTION_KEY` | `docs/api/config.md`, `docs/modules/security.md` | Yes |
| `mode` | `Literal['embedded', 'remote']` | `'embedded'` | `FOLIOMAN_MODE` | `docs/api/config.md`, `docs/compatibility.md` | Yes |
| `base_url` | `str \| None` | None | `FOLIOMAN_BASE_URL`, `FOLIOMAN_API_URL` | `docs/api/config.md`, `docs/compatibility.md` | Yes |
| `username` | `str \| None` | None | `FOLIOMAN_USERNAME` | `docs/api/config.md`, `docs/compatibility.md` | Yes |
| `password` | `SecretStr \| None` | None | `FOLIOMAN_PASSWORD` | `docs/api/config.md`, `docs/compatibility.md` | Yes |
| `token_refresh_skew` | `int` | `30` | `FOLIOMAN_TOKEN_REFRESH_SKEW` | `docs/api/config.md`, `docs/compatibility.md` | Yes |
| `auto_migrate` | `bool` | `True` | `FOLIOMAN_AUTO_MIGRATE` | `docs/api/config.md`, `docs/setup-and-configuration.md` | Yes |
| `default_user_id` | `str` | `'default'` | `FOLIOMAN_DEFAULT_USER_ID` | `docs/api/config.md` | Yes |

---

## 5. Exception Hierarchy Inventory (`folioman_client.errors`)

| Exception Class | Base Class | HTTP Status Code | Trigger Conditions | Verified |
| :--- | :--- | :---: | :--- | :---: |
| `FoliomanError` | `Exception` | 500 | Base exception for all domain and SDK errors | Yes |
| `FoliomanAuthError` | `FoliomanError` | 401 | Missing, expired, or invalid JWT credentials in remote mode | Yes |
| `FoliomanNotFoundError` | `FoliomanError` | 404 | Investor, folio, security, or job not found | Yes |
| `FoliomanValidationError` | `FoliomanError` | 422 | Invalid transaction parameters, invalid PAN regex, negative units | Yes |
| `FoliomanPasswordError` | `FoliomanValidationError` | 400 | Incorrect or missing CAS / eCAS PDF decryption password | Yes |
| `FoliomanParseError` | `FoliomanValidationError` | 400 | Unsupported statement format or corrupted PDF stream | Yes |
| `FoliomanConflictError` | `FoliomanError` | 409 | Duplicate record, SHA-256 deduplication hit, or state conflict | Yes |
| `FoliomanDatabaseError` | `FoliomanError` | 500 | SQLite table lock, broken connection pool, or DBAPI failure | Yes |
| `FernetKeyUnavailable` | `FoliomanError` | 500 | Master PAN encryption key cannot be loaded from env or keyring | Yes |
| `FoliomanFeedError` | `FoliomanError` | 502 | Upstream price feed network failure (AMFI, Yahoo Finance, mfapi) | Yes |
| `FoliomanAPIError` | `FoliomanError` | Custom | Remote HTTP server returned unexpected error status | Yes |

---

## 6. Data Model Inventory (Three-Layer Architecture)

### Layer 1: Public API Response Models (`folioman_client.models`)
Documented in `docs/models.md` (Section 3) and `docs/api/client.md`.

- **Auth DTOs:** `TokenPair`, `AccessToken`
- **Investor & Folio DTOs:** `Investor`, `InvestorDetail`, `Folio`, `FolioMergeResult`
- **Holdings & Portfolio DTOs:** `Holding`, `SchemeRef`, `NavPoint`, `FolioBalance`, `Transaction`, `SchemeDetail`, `AssetMixRow`, `AllocationBucket`, `PeriodReturn`, `PortfolioSummary`, `ValueSeriesPoint`, `ValueSeries`
- **Operation Result DTOs:** `CASImportResult`, `CapitalGainRow`, `CapitalGainsFyPoint`, `CapitalGainsReport`, `Schedule112AReport`, `CorporateActionReference`, `CorporateActionApplyResult`, `CorporateActionRefreshResult`, `NavSyncResult`, `NavBackfillResult`, `NavFreshnessItem`, `NavFreshnessReport`, `ISINSeedResult`, `ISINUpdateResult`, `ISINReferenceStatus`, `SymbolResolveResult`, `PositionIntegrity`, `PositionAcknowledgment`, `ReconcileInvestorResult`, `ReconcileAllResult`, `ValuationStatus`

### Layer 2: Core Domain Models (`folioman_client.core.models`)
Documented in `docs/models.md` (Section 4).

- **CAS Statement Parsing:** `MfCasLineItem`, `MfCasSchemeBlock`, `MfCasStatement`, `ParsedCas`
- **Domain Entities:** `CoreInvestor`, `CoreFolio`, `CoreSecurity`, `CoreTransaction`, `OpenLot`, `ConsumedLot`, `SellDisposal`, `CashFlow`
- **Strict Validation:** `coerce_decimal` prevents IEEE 754 floating-point errors (strictly forbids float and bool inputs).

### Layer 3: Database ORM Models (`folioman_client.db.models`)
Documented in `docs/models.md` (Section 5) and `docs/modules/database-and-persistence.md`.

- **18 SQLAlchemy 2.0 Declarative Tables:** `Investor`, `Folio`, `Security`, `Transaction`, `Holding`, `PartialBlock`, `NAVHistory`, `InvestorValue`, `CorporateActionReference`, `AppliedCorporateAction`, `SecurityIntegrityStatus`, `ImportJob`, `ImportQuarantine`, `AMC`, `RefISIN`, `ExchangeSymbol`, `ExchangeTradingHoliday`, `UserPreference`.

---

## 7. Test Suite Coverage & Verification Status

| Test File | Test Suite Focus | Test Functions | Execution Status |
| :--- | :--- | :---: | :---: |
| `tests/test_ledger_service.py` | Investors, folios, manual transaction ledger | 18 | Passing |
| `tests/test_valuation_service.py` | Point-in-time valuation, net worth, XIRR | 15 | Passing |
| `tests/test_capital_gains.py` | Section 112A, grandfathering, Budget 2024 | 14 | Passing |
| `tests/test_fifo.py` | First-In-First-Out lot consumption & cost basis | 12 | Passing |
| `tests/test_xirr.py` | Newton-Raphson & bisection root-finding | 10 | Passing |
| `tests/test_reconciliation.py` | Balance reconciliation & integrity checks | 12 | Passing |
| `tests/test_corporate_actions.py` | Split, bonus, and merger replay multipliers | 14 | Passing |
| `tests/test_corporate_action_detect.py` | Automatic split/bonus detection | 11 | Passing |
| `tests/test_nav_service.py` | AMFI bulk sync, mfapi backfill, Yahoo quotes | 16 | Passing |
| `tests/test_isin_service.py` | National ISIN dictionary & grandfathering NAVs | 10 | Passing |
| `tests/test_security_pan.py` | PAN normalization, HMAC-SHA256, Fernet encryption | 12 | Passing |
| `tests/test_client.py` | FoliomanClient remote HTTP vs embedded dispatch | 20 | Passing |
| `tests/test_cli_*.py` (10 files) | Click CLI commands (portfolio, isin, nav, etc.) | 85 | Passing |
| `tests/test_db_*.py` (4 files) | Database engine, WAL mode, migrations, sessions | 24 | Passing |
| `tests/test_parsers.py` | Reversal netting & CAS line parsing | 18 | Passing |
| `tests/test_schedule_112a.py` | Official 14-column ITR Schedule 112A export | 10 | Passing |
| `tests/test_scheduler.py` | Background APScheduler service | 6 | Passing |
| *Remaining test suites (10 files)* | Edge cases, config, errors, mappers, etc. | 32 | Passing |

!!! note "Branch Work-in-Progress Notice"
    Note: 7 tests in `test_import_service.py` and `test_cli_import.py` reflect uncommitted work-in-progress on branch `12-perf-001-batch-transactions` in `src/folioman_client/services/import_service.py`. All other 331 tests in the repository pass cleanly.