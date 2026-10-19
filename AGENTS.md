# AGENTS.md: Developer & AI Agent Guide for folioman-client

This document is the primary reference manual for AI coding agents (and human engineers) working on `folioman-client`. It details the architecture, design principles, invariants, commands, directory structures, and workflows required to extend and maintain this codebase safely and effectively.

---

## 1. Project Overview & Architecture

`folioman-client` is an embedded, typed Python 3.11+ portfolio engine and CLI for Indian personal finance, mutual funds, and equities.

Starting in `v0.2.0`, the library operates as a **zero-configuration embedded database application** (backed by SQLite via `aiosqlite` by default, with pluggable support for PostgreSQL via `psycopg3`). It can also function as an asynchronous HTTP REST SDK for a remote Folioman server.

### Core Capabilities
1. **CAS & eCAS Statement Ingestion**: Parses CAMS, KFintech, and NSDL/CDSL eCAS PDF statements via `casparser` and `cas_reader.py`. Uses SHA-256 deduplication hashes to ensure idempotent re-imports.
2. **Multi-Asset Price Feeds**: Automated NAV and price synchronization via AMFI bulk feeds, `mfapi.in`, Yahoo Finance, and NSE Bhavcopy archives.
3. **Financial Accounting & Math**: Strict First-In-First-Out (FIFO) lot allocation, Section 48 expense additions, and high-precision Newton-Raphson/bisection XIRR calculation.
4. **Indian Tax Engine (Schedule 112A)**: Full LTCG and STCG computations, Budget 2024 cutoff rules (July 23, 2024), and Section 112A grandfathering (Jan 31, 2018 FMV lookup).
5. **Non-Destructive Corporate Actions**: Replays stock splits, bonus issues, mergers, and demergers on-the-fly over immutable transaction ledgers without rewriting historical records.
6. **Command-Line Interface**: Click-based CLI (`folioman`) covering statements, ISIN databases, valuations, capital gains, and background schedulers.

---

## 2. Environment & Commands Quick-Reference

### 2.1 Python Environment & Tooling
- **Python Version**: `>= 3.11` (Tested on 3.11, 3.12, 3.13, 3.14).
- **Package Managers**: `uv` (recommended) or standard `pip` + `venv`.
- **Virtual Environment Location**: `.venv`

```bash
# Setup with uv:
uv sync --all-extras

# Or with pip:
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev,postgres]"
```

### 2.2 Test Suite Execution
Tests use `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"` is configured in `pyproject.toml`).

```bash
# Run all tests:
pytest

# Run tests with statement coverage:
pytest --cov=folioman_client tests/

# Run a specific test suite:
pytest tests/test_ledger_service.py

# Run a specific test function:
pytest tests/test_ledger_service.py -k test_create_and_get_investor

# Run fast (fail on first error):
pytest -x
```

### 2.3 Code Formatting & Linting
- **Formatter**: `black` (default config).
- **Linter**: `flake8` configured via `.flake8` (`max-line-length = 256`, ignore `E203, W503`).

```bash
# Check code style:
flake8 src tests

# Auto-format:
black src tests
```

### 2.4 CLI Execution
```bash
# Run CLI via installed entry point:
folioman --help

# Or via Python module directly:
python -m folioman_client.cli.main --help

# Example CLI commands:
folioman portfolio summary --investor-id 1
folioman isin sync
folioman nav refresh
```

---

## 3. Repository & Directory Structure

```
folioman-client/
├── docs/                        # Documentation & Codebase Audit Report
│   └── CODEBASE_AUDIT.md        # Comprehensive Staff+ Codebase Audit
├── src/
│   └── folioman_client/
│       ├── __init__.py          # Package exports (FoliomanClient, models, errors)
│       ├── client.py            # FoliomanClient facade & API resources
│       ├── config.py            # FoliomanSettings via pydantic-settings
│       ├── errors.py            # Custom exception hierarchy
│       ├── models.py            # Public Pydantic API response models
│       ├── types.py             # Type aliases and constants
│       ├── cli/                 # Click CLI commands
│       │   ├── main.py          # Root CLI group ('folioman')
│       │   ├── import_cmd.py    # Statement import commands ('import cas')
│       │   ├── isin.py          # ISIN sync & lookup commands
│       │   ├── ledger.py        # Investors, folios, manual transactions
│       │   ├── nav.py           # NAV refresh and backfill commands
│       │   ├── portfolio.py     # Portfolio summary & holdings inspection
│       │   ├── reconcile.py     # Statement unit reconciliation
│       │   ├── scheduler.py     # Background APScheduler service
│       │   ├── valuations.py    # Valuation recompute & history commands
│       │   └── capital_gains.py # Schedule 112A tax report generation
│       ├── core/                # Pure domain math, algorithms, and parsers
│       │   ├── fifo.py          # FIFO lot accounting engine
│       │   ├── xirr.py          # Newton-Raphson & bisection XIRR root-finding
│       │   ├── cas_reader.py    # Low-level CAS PDF extraction
│       │   ├── ecas_parser.py   # NSDL/CDSL eCAS parser
│       │   ├── parser.py        # Reversal netting & CAS line parsing
│       │   ├── corporate_actions.py       # Corporate action multiplier math
│       │   ├── corporate_action_detect.py # Corporate action autodetection
│       │   ├── models/          # Internal domain models (Pydantic v2)
│       │   │   ├── cas.py       # MfCasStatement, MfCasSchemeBlock, etc.
│       │   │   ├── decimal_fields.py # coerce_decimal validation helper
│       │   │   ├── investor.py  # Core Investor & Folio models
│       │   │   ├── security.py  # Core Security model & SecurityType
│       │   │   └── transaction.py # Core Transaction model & TransactionType
│       │   ├── price_feeds/     # Market data fetchers (AMFI, mfapi, Yahoo, NSE)
│       │   └── tax/             # Indian Capital Gains engine
│       │       ├── india.py     # Section 112A grandfathering & Budget 2024
│       │       ├── policy.py    # Holding period & tax rate policies
│       │       └── schedule_112a.py # ITR Schedule 112A CSV generation
│       ├── db/                  # Persistence layer
│       │   ├── engine.py        # create_folioman_engine & get_session_factory
│       │   ├── migrations.py    # init_schema() DDL initialization
│       │   └── models.py        # SQLAlchemy 2.0 ORM declarations (18 tables)
│       ├── security/            # PII protection & encryption
│       │   ├── pan.py           # PAN normalization, masking, encryption, hashing
│       │   └── keys.py          # Fernet key resolution
│       └── services/            # Application business services (10 services)
│           ├── ledger_service.py           # Investors, folios, manual ledger
│           ├── import_service.py           # Statement parsing & ingestion
│           ├── valuation_service.py        # Holdings, valuations, XIRR
│           ├── nav_service.py              # NAV updates & gap backfills
│           ├── capital_gains_service.py    # Tax gain calculations
│           ├── corporate_action_service.py # Split/bonus persistence & replay
│           ├── reconciliation_service.py   # Statement vs ledger reconciliation
│           ├── isin_service.py             # 100k+ master ISIN dictionary
│           ├── equity_symbol_service.py    # Stock ticker resolution
│           ├── scheduler.py                # Background APScheduler wrapper
│           ├── projected_ledger.py         # Dynamic ledger replay with splits
│           └── mappers.py                  # Model transformation adapters
└── tests/                       # Pytest test suite (31 test files, 224 tests)
```

---

## 4. Critical Engineering Invariants (MUST FOLLOW)

When modifying or adding code in this repository, strictly adhere to these rules:

### Rule 1: Strict Decimal Financial Discipline
- **NEVER use IEEE 754 `float`** for currency, monetary amounts, share/unit counts, NAVs, prices, or taxes.
- **ALWAYS use `decimal.Decimal`**.
- Use `coerce_decimal` from `folioman_client.core.models.decimal_fields` for Pydantic fields. It explicitly rejects `bool` and `float` inputs.
- When formatting strings or CSVs, trim trailing zeroes properly without converting to `float`:
  ```python
  from decimal import Decimal

  d = Decimal("100.5000")
  # Correct formatting:
  formatted = f"{d:.4f}"
  ```

### Rule 2: PAN & PII Security Invariants
- Permanent Account Numbers (PANs) are highly sensitive financial identifiers.
- **NEVER log plaintext PANs or statement passwords.**
- **NEVER store plaintext PANs in database columns.**
- In the database, the `Investor` table stores:
  1. `pan_encrypted`: Plaintext PAN encrypted via Fernet (`LargeBinary`).
  2. `pan_hash`: Keyed HMAC-SHA256 digest (`String(64)`) used for deterministic SQL indexing.
- Use the helpers in `folioman_client.security.pan`:
  ```python
  from folioman_client.security.pan import normalize_pan, mask_pan, encrypt_pan, hash_pan

  pan_clean = normalize_pan(raw_pan)
  masked = mask_pan(pan_clean)  # e.g., "XXXXXX234F"
  enc_bytes = encrypt_pan(pan_clean)  # Store in pan_encrypted
  lookup_hash = hash_pan(pan_clean)  # Store in pan_hash
  ```

### Rule 3: Transaction Immutability & Corporate Actions
- Rows in the `Transaction` table (`db/models.py`) represent historical real-world financial events and are **immutable**.
- When a company undergoes a stock split, bonus issue, or merger, **do NOT mutate historical buy transaction units or prices**.
- Corporate actions are recorded in the `CorporateAction` table and replayed on read via `ProjectedLedger` (`services/projected_ledger.py`) or factored into holding calculations in `ValuationService`.

### Rule 4: Exception Hierarchy & Error Propagation
- Do NOT raise bare `ValueError` or generic `Exception` in public service methods or client resources.
- Use or extend the domain exceptions in `folioman_client.errors`:
  - `FoliomanError` (Base exception)
  - `FoliomanNotFoundError` (Raised when an investor, folio, security, or job is not found)
  - `FoliomanValidationError` (Invalid input or unparseable statement)
  - `FoliomanAuthError` (Authentication / token failures)
  - `FoliomanConflictError` (Duplicate records / state conflicts)

### Rule 5: Database Transactions & Lifecycle
- Always use async context managers for sessions:
  ```python
  from folioman_client.db.engine import get_session_factory

  session_factory = get_session_factory(self.engine)
  async with session_factory() as session:
      async with session.begin():
          # Atomic database operations here
          session.add(my_model)
  ```
- **Do NOT invoke `init_schema()` inside CRUD methods.** `init_schema()` performs schema introspection and DDL execution under exclusive table locks (`engine.begin()`). It should only be called once during application setup or database bootstrap.

### Rule 6: Avoid N+1 Query Patterns
- When checking for existing records in batch imports (such as deduplication checks in `ImportService`), do not run individual queries in a loop.
- **Batch lookups using `IN` clauses**:
  ```python
  stmt = select(Transaction.dedup_key).where(Transaction.dedup_key.in_(batch_keys))
  existing_keys = set((await session.execute(stmt)).scalars().all())
  ```

### Rule 7: Valuation Cache Invalidation
- The `InvestorValue` table stores cached daily portfolio net worth history.
- When new transactions are imported, manually recorded, or updated, always trigger recomputation:
  ```python
  await valuation_service.queue_recompute(
      investor_id=investor_id, from_date=earliest_date
  )
  ```

### Rule 8: Async/Sync Concurrency Boundaries
- Do NOT call blocking synchronous functions (like `time.sleep()`, synchronous `requests.get()`, or long CPU loops) inside async methods. Use `asyncio.sleep()` or run CPU-bound work via an executor.
- Do NOT share an `AsyncEngine` across worker threads with separate event loops (e.g. APScheduler background threads). Schedulers should either use the main event loop or create an engine dedicated to that worker thread.

---

## 5. Understanding the Three Model Layers

A common point of confusion in `folioman-client` is the existence of three separate model hierarchies. Understand their roles before authoring changes:

| Layer | Location | Base Class | Purpose |
| :--- | :--- | :--- | :--- |
| **API Response Models** | `folioman_client.models` | `pydantic.BaseModel` | Public facing DTOs returned by `FoliomanClient` resources (e.g., `PortfolioSummary`, `HoldingSummary`, `InvestorProfile`). |
| **Core Domain Models** | `folioman_client.core.models` | `pydantic.BaseModel` | Intermediate structures used during CAS PDF parsing, statement processing, and math calculations (e.g., `MfCasStatement`, `CoreSecurity`, `CoreTransaction`). |
| **Database ORM Models** | `folioman_client.db.models` | `sqlalchemy.orm.DeclarativeBase` (`Base`) | 18 SQLAlchemy ORM database tables persisted to SQLite / PostgreSQL (e.g., `Investor`, `Folio`, `Security`, `Transaction`, `NavHistory`). |

**Translation Layer**: Use `folioman_client.services.mappers` to translate between these layers. Keep transformations lossless wherever possible.

---

## 6. How-To Recipes for Common Development Tasks

### 6.1 Writing Unit Tests with Isolated In-Memory Database
Always use an in-memory SQLite engine (`sqlite+aiosqlite:///:memory:`) for fast, isolated service testing:

```python
import pytest
from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.services.ledger_service import LedgerService


@pytest.fixture
async def ledger_service():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = LedgerService(engine=engine)
    try:
        yield service
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_my_feature(ledger_service: LedgerService):
    investor = await ledger_service.create_investor(
        user_id="user_123", name="Test Investor", pan="ABCDE1234F"
    )
    assert investor["name"] == "Test Investor"
    assert investor["pan_masked"] == "XXXXXX234F"
```

### 6.2 Adding a New CLI Command
1. Create or open the relevant module in `src/folioman_client/cli/` (e.g., `portfolio.py`).
2. Define a Click command under the appropriate group:
   ```python
   import click
   from folioman_client.cli.main import cli
   from folioman_client.db.engine import create_folioman_engine
   from folioman_client.config import get_settings


   @cli.group("custom")
   def custom_group():
       """Custom operations."""
       pass


   @custom_group.command("run")
   @click.option("--investor-id", type=int, required=True, help="Investor ID")
   def run_custom(investor_id: int):
       """Execute custom logic."""
       settings = get_settings()
       # Execute logic...
       click.echo(f"Executed for investor {investor_id}")
   ```
3. Ensure the command group is registered in `src/folioman_client/cli/main.py`.
4. Write corresponding tests in `tests/test_cli_*.py` using Click's `CliRunner`.

### 6.3 Adding a New Database Table / ORM Model
1. Declare the model in `src/folioman_client/db/models.py` inheriting from `Base`:
   ```python
   class NewEntity(Base):
       __tablename__ = "new_entities"

       id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
       name: Mapped[str] = mapped_column(String(255), nullable=False)
       created_at: Mapped[datetime] = mapped_column(
           DateTime, default=lambda: datetime.now(timezone.utc)
       )
   ```
2. Export the model in `src/folioman_client/db/models.py` and `__all__`.
3. In `src/folioman_client/db/migrations.py`, add index or table creation logic if special pragmas are needed.
4. Add verification tests in `tests/test_migrations.py`.

---

## 7. Known Architectural Hotspots & Refactoring Guidance

Refer to [`docs/CODEBASE_AUDIT.md`](file:///d:/GitHub_Clones/folioman-client/docs/CODEBASE_AUDIT.md) for full audit findings. When working in these areas, be mindful of ongoing refactoring targets:

1. **`FoliomanClient` God Class (`ARCH-001`)**:
   `FoliomanClient` currently manages both remote HTTP routing and embedded database engines. When updating client resource methods, ensure both remote HTTP dispatch and embedded service fallback are properly implemented, or respect query filters.
2. **Monolithic Corporate Action Detector (`COMP-001`)**:
   `CorporateActionDetect._detect_split_bonus_merger` in `core/corporate_action_detect.py` is a 462-line function with 38 branches. Avoid adding further nested branches; prefer extracting modular detection helper strategies.
3. **Dead Code Modules (`SMELL-002`)**:
   `src/folioman_client/core/dividend_attribution.py`, `src/folioman_client/core/identity_remap.py`, and `src/folioman_client/core/opening_lot.py` are currently unreferenced with 0% test coverage. Do not build new dependencies on these without verifying their intended design.

---

## 8. Summary Checklist for Pull Requests & Agent Tasks

Before concluding any code change or submitting a pull request:

- [ ] All prices, NAVs, amounts, and units use `Decimal` (no `float`).
- [ ] PANs are masked in logs and encrypted/hashed at rest.
- [ ] No `init_schema()` calls inside per-request CRUD methods.
- [ ] All database queries are batched where appropriate (no N+1 loops).
- [ ] New service methods raise `FoliomanError` subclasses, not bare `ValueError`.
- [ ] Unit tests pass: `pytest` exits with code 0.
- [ ] Code formatting & linting pass: `black --check src tests` and `flake8 src tests`.
- [ ] No secrets or `.env` files committed.
