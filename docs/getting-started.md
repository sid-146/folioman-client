# Getting Started

This guide walks you through installing `folioman-client`, initializing the database, importing a Consolidated Account Statement (CAS), syncing market NAVs, and inspecting portfolio metrics and capital gains.

---

## 1. Installation

Install the package using your preferred package manager:

=== "pip"

    ```bash
    pip install folioman-client
    ```

=== "uv"

    ```bash
    uv add folioman-client
    ```

=== "poetry"

    ```bash
    poetry add folioman-client
    ```

### Optional PostgreSQL Support

If you plan to use a PostgreSQL database instead of the default SQLite:

```bash
pip install "folioman-client[postgres]"
```

---

## 2. Quick CLI Tour

`folioman-client` provides a terminal command `folioman`.

### Step A: Initialize and Seed Reference Data

On a fresh installation, seed the national ISIN reference dictionary:

```bash
folioman isin seed
```

This populates the `ref_schemes`, `ref_isins`, and `ref_grandfathering_navs` tables inside your database (defaulting to `~/.folioman/folioman.db`).

### Step B: Ingest a CAS PDF

Download your Consolidated Account Statement PDF from CAMS, KFintech, or NSDL/CDSL, and import it:

```bash
folioman import cas ~/Downloads/CAS_Jan_2026.pdf --password "MYPAN1234F"
```

The CLI parses all schemes and transactions, normalizes folios, deduplicates historical rows, and establishes the investor profile.

### Step C: Fetch Latest Market NAVs

Sync latest daily NAVs and market closing quotes:

```bash
folioman navs refresh
```

To backfill historical NAV gaps back to the earliest transaction date:

```bash
folioman navs backfill
```

### Step D: Reconcile Balances

Verify your trade ledger against the reported statement closing units:

```bash
folioman reconcile all
```

---

## 3. Python SDK Quickstart

You can perform the exact same workflows programmatically within your Python code.

### Minimal Script

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    # 1. Connect (defaults to SQLite; or pass database_url="postgresql+psycopg://...")
    async with FoliomanClient() as client:
        # 2. Ingest statement
        print("Importing CAS statement...")
        job = await client.imports.cas_pdf(
            file_path="CAS_Jan_2026.pdf",
            password="ABCDE1234F",
        )
        print(f"Imported successfully! Created {job.get('transactions_created', 0)} transactions.")

        # 3. Refresh market NAVs
        print("Refreshing market NAVs...")
        await client.navs.refresh()

        # 4. List investors
        investors = await client.investors.list()
        for inv in investors:
            print(f"\nInvestor: {inv.name} (ID: {inv.id})")

            # 5. Fetch full portfolio summary
            summary = await client.portfolio.get(inv.id)
            print(f"  Total Portfolio Value: INR {summary.total_inr:,.2f}")
            print(f"  Holdings Count:       {summary.holdings_count}")
            if summary.day_change_inr is not None:
                print(f"  Day Change:           INR {summary.day_change_inr:,.2f}")
            if summary.xirr is not None:
                print(f"  Annualized XIRR:      {summary.xirr * 100:.2f}%")

            # 6. Inspect priced holdings
            holdings = await client.holdings.list(inv.id)
            print(f"  Priced holdings:      {len(holdings)}")
            for h in holdings[:5]:
                val = f"INR {h.value_inr:,.2f}" if h.value_inr is not None else "Unpriced"
                print(f"    - {h.name}: {h.units} units | {val}")

            # 7. Generate Realized Capital Gains Report (Schedule 112A)
            gains = await client.capital_gains.get(inv.id, fy="2024-25")
            print(f"  FY 2024-25 Realized LTCG: INR {gains.ltcg_total:,.2f}")
            print(f"  FY 2024-25 Realized STCG: INR {gains.stcg_total:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Connecting to PostgreSQL or MySQL

To switch from SQLite to PostgreSQL or MySQL, pass the connection URL to the client or set the `FOLIOMAN_DATABASE_URL` environment variable:

### Via Environment Variable

```bash
export FOLIOMAN_DATABASE_URL="postgresql+psycopg://postgres:secret@localhost:5432/my_portfolio"
```

### In Python Code

```python
from folioman_client import FoliomanClient

client = FoliomanClient(
    database_url="postgresql+psycopg://postgres:secret@localhost:5432/my_portfolio"
)
```

The library automatically creates all tables and indexes, seeds reference dictionaries, and configures connection pooling.

---

## Next Steps

- Explore [Storage & Database Configuration](configuration.md) to learn about SQLite concurrency and PostgreSQL setup.
- Read the [CLI Reference](cli.md) for full terminal command options.
- Review the [Python Client SDK](client.md) for detailed resource APIs and methods.
