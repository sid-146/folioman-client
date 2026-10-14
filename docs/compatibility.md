# Backward Compatibility & Migration

`folioman-client` underwent a major architectural evolution between **v0.1.0** and **v0.2.0**. This guide documents what remains backward-compatible with older codebases, how remote client mode operates, the official deprecation timeline, and steps to migrate to the embedded engine.

---

## Evolution: Remote SDK to Embedded Engine

- **v0.1.0 (Remote REST Client)**: Originally, `folioman-client` was a thin, asynchronous Python HTTP client connecting to an external Folioman backend daemon via REST APIs, managing JWT authentication and serializing responses.
- **v0.2.0 (Embedded Local-First Engine)**: Folioman transitioned into a self-contained, high-performance portfolio accounting engine and CLI. It runs directly inside your application process, backed by SQLAlchemy (SQLite, PostgreSQL, or MySQL), with built-in CAS statement parsers, NAV pricing feeds, FIFO valuation engines, and capital gains tax calculators.

To ensure existing integrations and scripts built against v0.1.0 continue to work without breaking, **backward compatibility was deliberately preserved** for the core remote client workflows.

---

## What Remains Backward-Compatible

### 1. `FoliomanClient` Remote Mode via `base_url`

When `base_url` is provided to `FoliomanClient` (or when `mode="remote"` is specified), the client operates in **remote mode**:

```python
from folioman_client import FoliomanClient

# v0.1.0 style instantiation remains functional in v0.2.0:
client = FoliomanClient(
    base_url="https://api.folioman.example.com",
    username="advisor_alpha",
    password="super_secret_password",
)
```

In remote mode (`client.is_remote is True`):
- Internal HTTP calls are dispatched via `httpx` to the configured remote host.
- The path is automatically prefixed with `/api` (e.g. `/investors/` resolves to `https://api.folioman.example.com/api/investors/`).
- The following resources continue to route over HTTP:
  - `client.investors.list()` & `client.investors.get(id)`
  - `client.portfolio.get(investor_id)` & `client.portfolio.history(investor_id)`
  - `client.holdings.list(investor_id)`
  - `client.transactions.list(...)` & `client.transactions.create(txn)`

### 2. JWT Authentication Lifecycle

The remote authentication subsystem (`folioman_client.auth.JWTAuthManager`) remains operational:
- **Token Acquisition**: Automatically issues `POST /api/auth/token/pair` with credentials to obtain an access and refresh token.
- **Token Refresh**: Automatically monitors token expiration with a 30-second skew buffer and requests a new token via `POST /api/auth/token/refresh`.
- **401 Recovery**: Intercepts HTTP 401 Unauthorized responses, attempts a refresh under a concurrency-safe lock (`asyncio.Lock()`), and retries the request transparently.
- **Header Injection**: Attaches `Authorization: Bearer <token>` to outgoing requests.

### 3. Environment Variables & Settings

The `FoliomanSettings` class (`folioman_client.config`) continues to accept legacy environment variables:

| Setting Attribute | Environment Variable(s) | Description |
| :--- | :--- | :--- |
| `base_url` | `FOLIOMAN_BASE_URL`, `FOLIOMAN_API_URL` | Legacy REST API base endpoint |
| `username` | `FOLIOMAN_USERNAME` | Legacy API username |
| `password` | `FOLIOMAN_PASSWORD` | Legacy API password |

Aliases such as `settings.folioman_url`, `settings.folioman_username`, and `settings.folioman_password` are also preserved.

### 4. Legacy Models & HTTP Errors

- Models such as `TokenPair`, `AccessToken`, and `RefreshToken` remain importable from `folioman_client.models` and `folioman_client.auth`.
- HTTP status code exceptions (`FoliomanAuthError`, `FoliomanNotFoundError`, `FoliomanValidationError`, `FoliomanConflictError`, `FoliomanRateLimitError`, `FoliomanServerError`, `FoliomanAPIError`) continue to be raised for remote HTTP failures.

---

## Limitations in Remote Mode

The new capabilities introduced in v0.2.0 run against a local or database-backed engine. They are **not available** over remote REST mode:

| Feature / Sub-resource | Embedded Mode (v0.2.0) | Remote Mode (v0.1.0) |
| :--- | :---: | :---: |
| Investor & Portfolio Queries |  Available |  Available (via REST) |
| Holdings & Transactions |  Available |  Available (via REST) |
| CAS PDF & Excel Parser (`client.imports.*`) |  Available |  Not supported (requires DB engine) |
| AMFI & BSE NAV Sync (`client.navs.*`) |  Available |  Not supported (requires DB engine) |
| National ISIN Seed (`client.isin.*`) |  Available |  Not supported (requires DB engine) |
| Daily Net-Worth Valuation Engine |  Available |  Not supported (requires DB engine) |
| Capital Gains & Schedule 112A Tax Reports |  Available |  Not supported (requires DB engine) |
| CAS vs Ledger Reconciliation |  Available |  Not supported (requires DB engine) |
| Corporate Action Engine (Stock Splits / Bonuses) |  Available |  Not supported (requires DB engine) |

---

## Deprecation Notice: Remote Mode Removal

> [!WARNING] Deprecation Notice
> Remote REST client mode (`base_url`, `username`, `password`, `JWTAuthManager`, and HTTP dispatching) is **deprecated** as of `v0.2.0`.
>
> It will be **completely removed in a future release** (planned for `v0.3.0` / `v1.0.0`).
>
> Moving forward, `folioman-client` will exclusively operate as an embedded, self-contained Python engine with direct database access.

If your architecture requires a separate HTTP microservice, we recommend wrapping the `folioman-client` embedded engine inside a lightweight FastAPI or Litestar service within your infrastructure.

---

## Migration Guide: Moving to Embedded Mode

Migrating from remote client mode to embedded mode requires minimal code changes and eliminates the need to run and maintain a separate Folioman daemon.

### Step 1: Update Client Initialization

Replace remote URL configurations with a local SQLite file or PostgreSQL database connection:

#### Before (v0.1.0 Remote Client):
```python
from folioman_client import FoliomanClient

async with FoliomanClient(
    base_url="https://api.folioman.example.com",
    username="advisor_alpha",
    password="super_secret_password",
) as client:
    investors = await client.investors.list()
```

#### After (v0.2.0 Embedded Engine):
```python
from folioman_client import FoliomanClient

# Local SQLite (zero-configuration, WAL mode enabled)
async with FoliomanClient(
    database_url="sqlite+aiosqlite:///folioman.db",
    user_id="advisor_alpha",  # Logical tenant scope
) as client:
    investors = await client.investors.list()
```

For production or cloud deployments, point to PostgreSQL:

```python
async with FoliomanClient(
    database_url="postgresql+psycopg://user:pass@localhost:5432/portfolio",
    user_id="advisor_alpha",
) as client:
    investors = await client.investors.list()
```

### Step 2: Replace Backend Imports with Direct Ingestion

In v0.1.0, statement files had to be uploaded to the remote server. In v0.2.0, you can parse CAS PDF statements directly in Python:

```python
async with FoliomanClient(database_url="sqlite+aiosqlite:///folioman.db") as client:
    # Directly parse encrypted CAMS/KFintech CAS statement
    summary = await client.imports.cas_pdf(
        file_path="cams_cas.pdf",
        password="investor_pan_or_pass",
    )
    print(
        f"Imported {summary.get('transactions_created', 0)} transactions into local database."
    )
```

### Step 3: Run Valuations and Tax Locally

Instead of querying a remote server for portfolio valuation and capital gains, compute them instantly using the embedded calculation engine:

```python
async with FoliomanClient(database_url="sqlite+aiosqlite:///folioman.db") as client:
    # 1. Update latest mutual fund NAVs from AMFI
    await client.navs.refresh(types=["mf"])

    # 2. Compute portfolio valuation as of today
    portfolio = await client.portfolio.summary(investor_id=1)
    val = float(portfolio.total_inr) if portfolio.total_inr else 0.0
    print(f"Total Portfolio Value: INR {val:,.2f}")

    # 3. Compute Schedule 112A capital gains report for FY 2024-25
    gains = await client.capital_gains.get(
        investor_id=1,
        fy="2024-25",
    )
    stcg = float(gains.stcg_total) if gains.stcg_total else 0.0
    ltcg = float(gains.ltcg_total) if gains.ltcg_total else 0.0
    print(f"LTCG: INR {ltcg:,.2f} | STCG: INR {stcg:,.2f}")
```

### Summary of Configuration Mapping

| v0.1.0 Remote Setting | v0.2.0 Embedded Equivalent | Notes |
| :--- | :--- | :--- |
| `base_url` | `database_url` | Switch from REST endpoint to DB connection string |
| `username` / `password` | `user_id` | Logical tenant/advisor scope in multi-tenant DB |
| `FOLIOMAN_BASE_URL` | `FOLIOMAN_DATABASE_URL` | Configure via `.env` or system environment |
| Remote Folioman server | Embedded SQLite / PostgreSQL | No separate daemon or microservice needed |
