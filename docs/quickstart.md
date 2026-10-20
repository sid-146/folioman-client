# Quickstart Guide

This quickstart guides you through setting up an embedded portfolio engine, creating an investor profile, importing transactions, fetching live market NAVs, and calculating real-time portfolio valuation and XIRR.

---

## 1. 5-Minute Python Quickstart

Create a Python script `demo.py`:

```python
import asyncio
from datetime import date
from decimal import Decimal
from folioman_client import FoliomanClient


async def main():
    # 1. Initialize embedded engine (zero-config SQLite)
    client = FoliomanClient()

    # 2. Create an investor profile (PAN is automatically masked and encrypted)
    investor = await client.investors.create(
        name="Vikram Mehta", pan="ABCDE1234F", email="vikram@example.com"
    )
    print(
        f"Created Investor: {investor.name} (ID: {investor.id}, PAN: {investor.pan_masked})"
    )

    # 3. Create a Mutual Fund Folio
    folio = await client.folios.create(
        investor_id=investor.id,
        folio_number="1234567/89",
        folio_type="mf",
        amc_code="HDFC_MF",
    )
    print(f"Created Folio: {folio.folio_number} (ID: {folio.id})")

    # 4. Record a Purchase Transaction
    txn = await client.transactions.create(
        folio_id=folio.id,
        isin="INF179K01BE2",  # HDFC Flexi Cap Fund - Direct Plan - Growth
        date=date(2023, 1, 15),
        type="BUY",
        units=Decimal("500.000"),
        nav=Decimal("1050.2500"),
        amount=Decimal("525125.00"),
        description="SIP Investment",
    )
    print(f"Recorded Buy: {txn.units} units @ INR {txn.nav} (Txn ID: {txn.id})")

    # 5. Refresh NAV prices from official AMFI feeds
    sync_report = await client.navs.refresh()
    print(f"NAV Refresh Complete: {sync_report.updated_count} schemes updated")

    # 6. Compute Real-Time Portfolio Valuation & Annualized XIRR
    portfolio = await client.portfolio.get(investor_id=investor.id)
    print("\n--- Portfolio Summary ---")
    print(f"Total Invested Value : INR {portfolio.total_cost:,.2f}")
    print(f"Current Market Value : INR {portfolio.total_value:,.2f}")
    print(
        f"Unrealized Gain / P&L: INR {portfolio.unrealized_gain:,.2f} ({portfolio.gain_percentage:.2f}%)"
    )
    print(f"Annualized XIRR      : {portfolio.xirr:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
```

Run the script:
```bash
python demo.py
```

---

## 2. 3-Minute CLI Quickstart

If you prefer using the command line rather than Python code, `folioman-client` includes a Click-based CLI:

### Step 1: Initialize Reference Data
```bash
folioman isin seed
```

### Step 2: Import a CAS Statement PDF
Download your monthly CAMS, KFintech, or NSDL/CDSL eCAS PDF statement and import it:
```bash
folioman import cas ~/Downloads/CAS_Statement.pdf --password "MYPAN1234F"
```
*Folioman automatically decrypts the statement, creates the investor profile, normalizes folios, cancels reversals, and inserts all transactions idempotently.*

### Step 3: Refresh Current Market NAVs
```bash
folioman nav refresh
```

### Step 4: Inspect Portfolio Valuation & Holdings
```bash
# View portfolio summary table
folioman portfolio summary --investor-id 1

# View scheme-by-scheme holdings
folioman portfolio holdings --investor-id 1
```

### Step 5: Generate Indian Capital Gains Tax Report (Schedule 112A)
```bash
folioman capital-gains schedule-112a --investor-id 1 --fy 2024-2025 --csv tax_return.csv
```
*Outputs an official 14-column Schedule 112A CSV file ready for Form ITR-2 or ITR-3 e-filing.*

---

## Where to Go Next

- **[System Architecture](architecture.md)**: Deep dive into the 3-layer architecture, FIFO engine, and database schema.
- **[Application Services Reference](api/services.md)**: Explore the 10 domain services.
- **[Indian Tax Engine (Schedule 112A)](modules/core-tax.md)**: Understand Section 112A grandfathering and Budget 2024 cutoff rules.
- **[Python SDK Client Guide](client.md)**: Detailed examples for all 13 client resources.
