# folioman-client

[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-blue.svg)](https://pypi.org/project/folioman-client/)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://pypi.org/project/folioman-client/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-GitHub_Pages-blue.svg)](https://sid-146.github.io/folioman-client/)

An embedded, typed Python portfolio engine and CLI for Indian mutual funds and equities.

`folioman-client` provides an all-in-one, serverless financial engine for parsing Consolidated Account Statements (CAMS/KFintech CAS and NSDL/CDSL eCAS), fetching live NAVs and market prices, running FIFO lot accounting, calculating annualized XIRR, replaying corporate actions, and computing Schedule 112A Indian capital gains taxes.

> [!NOTE]
> **Embedded & Self-Contained:** Starting with `v0.2.0`, `folioman-client` is a pure embedded library and CLI tool. It does **not** require a running backend server, Docker daemon, or Django setup. It uses a zero-configuration SQLite database by default, with pluggable support for PostgreSQL and MySQL.

---

## Key Features

- **Zero-Setup Embedded Storage**: Runs out of the box using SQLite (configured with WAL mode and concurrency guards). Opt in to PostgreSQL or MySQL via a standard SQLAlchemy connection URL (`postgresql+psycopg://...`).
- **Unified Single Database**: 100% of data—user portfolios, transactions, daily NAV history, and the 100,000-row national ISIN reference dictionary—lives in your selected database.
- **Statement Ingestion (CAS & eCAS)**: Native parsing of CAMS, KFintech, and NSDL/CDSL eCAS PDF statements powered by `casparser`, with idempotent SHA-256 deduplication and out-of-order statement convergence.
- **Automated Price Feeds**: Multi-asset price fetching from `mfapi.in`, AMFI bulk text feeds, Yahoo Finance, and NSE Bhavcopy archives, with automatic historical gap backfilling.
- **Financial Math & Returns**: Strict First-In-First-Out (FIFO) lot accounting, Section 48 brokerage cost additions, and high-precision Newton-Raphson / bisection XIRR root-solving.
- **Indian Capital Gains Tax (Schedule 112A)**: Full LTCG and STCG computation, Section 112A grandfathering (31-Jan-2018 FMV lookup), and Budget 2024 tax regime cutoff (23-Jul-2024).
- **Non-Destructive Corporate Actions**: Dynamic replay of stock splits, bonuses, mergers, and demergers over immutable transaction ledgers on read.
- **Comprehensive CLI Suite**: Manage statements, ISIN dictionaries, NAV refreshes, and valuations directly from the terminal via the `folioman` command.

---

## Installation

Install via `pip`:

```bash
pip install folioman-client
```

Or using `uv`:

```bash
uv add folioman-client
```

### PostgreSQL Support (Optional)

If connecting to PostgreSQL:

```bash
pip install "folioman-client[postgres]"
```

---

## Quickstart

### 1. Python API

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    # Zero-setup: defaults to local SQLite; or pass PostgreSQL / MySQL URL:
    # FoliomanClient(database_url="postgresql+psycopg://user:pass@localhost/portfolio")
    async with FoliomanClient() as client:
        # 1. Ingest a CAMS / KFintech or eCAS statement
        print("Importing CAS statement...")
        job = await client.imports.cas_pdf(
            file_path="cas_statement.pdf",
            password="INVESTOR_PAN",
        )
        print(f"Import complete! Processed {job.result.get('transactions_created', 0)} transactions.")

        # 2. Sync latest market NAVs & stock quotes
        print("Refreshing market prices...")
        await client.navs.refresh()

        # 3. Query portfolio summary & metrics
        summary = await client.portfolio.get(investor_id=1)
        print(f"Portfolio Value: INR {summary.total_inr:,.2f}")
        print(f"Portfolio XIRR: {summary.xirr * 100:.2f}%" if summary.xirr else "XIRR: N/A")

        # 4. Inspect priced holdings
        holdings = await client.holdings.list(investor_id=1)
        for h in holdings:
            print(f"- {h.name}: {h.units} units | Value: INR {h.value_inr:,.2f}")

        # 5. Generate Realized Capital Gains (Schedule 112A)
        gains = await client.capital_gains.get(investor_id=1, fy="2024-25")
        print(f"FY 2024-25 Realized LTCG: INR {gains.summary.ltcg_inr:,.2f}")
        print(f"FY 2024-25 Realized STCG: INR {gains.summary.stcg_inr:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Command-Line Interface (CLI)

`folioman-client` includes a comprehensive command-line tool `folioman`. All commands accept an optional `--db` flag (or `FOLIOMAN_DATABASE_URL` environment variable).

```bash
# Seed or update the national ISIN reference dictionary in your database
folioman isin seed
folioman isin update

# Ingest statements
folioman import cas statement.pdf --password "ABCDE1234F" --investor-id 1
folioman import csv equity_trades.csv --investor-id 1

# Price feeds & historical backfills
folioman navs refresh
folioman navs backfill --force
folioman symbols resolve

# Maintenance & reconciliations
folioman reconcile all
folioman corporate-actions refresh
folioman valuations extend

# Optional persistent background scheduler
folioman scheduler run
```

---

## Database Configuration

Storage is fully pluggable via standard SQLAlchemy connection URLs:

| Database Engine      | Example Connection URL                                    | Notes                                               |
| :------------------- | :-------------------------------------------------------- | :-------------------------------------------------- |
| **SQLite (Default)** | `sqlite+aiosqlite:///~/.folioman/folioman.db`             | Zero setup. Automatic WAL mode & busy timeout.      |
| **PostgreSQL**       | `postgresql+psycopg://user:pass@localhost:5432/portfolio` | Recommended for multi-user, Docker, and production. |
| **MySQL / MariaDB**  | `mysql+aiomysql://user:pass@localhost:3306/portfolio`     | Connection pooling enabled.                         |

Configure via code or environment variable:

```bash
export FOLIOMAN_DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/portfolio"
```

---

## Attribution & Acknowledgements

`folioman-client` is an independent, clean-room Python library implementation under the **MIT License**. It is inspired by the architectural concepts, data schemas, and calculation rules of the open-source project **[Folioman](https://github.com/codereverser/folioman)** by `codereverser`. We gratefully acknowledge the Folioman project and its contributors.

---

## License

This project is licensed under the [MIT License](LICENSE).
