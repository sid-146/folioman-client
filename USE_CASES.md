# Sample Use-Cases for Folioman Client

`folioman-client` is a serverless, embedded Python financial engine designed for Indian mutual funds, equities, ETFs, bonds, and digital assets. It can be embedded directly into CLI tools, desktop apps, Jupyter notebooks, or production web backends (FastAPI, Django, Flask).

This document outlines key real-world use cases with complete, runnable code examples.

---

## Table of Contents

1. [Automated Tax Filing & Schedule 112A Capital Gains Engine](#1-automated-tax-filing--schedule-112a-capital-gains-engine)
2. [Private & Self-Hosted Personal Net Worth Tracker](#2-private--self-hosted-personal-net-worth-tracker)
3. [Multi-Client Family Office & RIA Advisor Backend](#3-multi-client-family-office--ria-advisor-backend)
4. [Demat Tradebook vs. Statement Reconciliation & Audit](#4-demat-tradebook-vs-statement-reconciliation--audit)
5. [Automated Daily Portfolio Valuation & NAV Scheduler](#5-automated-daily-portfolio-valuation--nav-scheduler)
6. [Multi-Asset Global Portfolio (Mutual Funds + US Stocks + Crypto)](#6-multi-asset-global-portfolio-mutual-funds--us-stocks--crypto)

---

## 1. Automated Tax Filing & Schedule 112A Capital Gains Engine

### Target Audience
Chartered Accountants (CAs), tax platforms, and individual investors preparing ITR-2 or ITR-3 income tax returns.

### The Problem
Calculating capital gains for Indian mutual funds and equities is complex due to:
* **Section 112A Grandfathering**: Determining Fair Market Value (FMV) as of 31-Jan-2018.
* **Budget 2024 Regime Split**: Transactions on or after **23-Jul-2024** use new LTCG (12.5%) and STCG (20%) rates, while earlier transactions use 10% and 15%.
* **Section 50AA**: Specified debt mutual funds purchased after 1-Apr-2023 are taxed at slab rates as STCG regardless of holding period.

### Solution with `folioman-client`
Folioman evaluates disposal lots via strict First-In-First-Out (FIFO) accounting, performs Section 112A grandfathering lookups, and categorizes realized gains.

```python
import asyncio
from folioman_client import FoliomanClient


async def generate_tax_report():
    async with FoliomanClient() as client:
        # Ingest statement (CAMS / KFintech CAS)
        await client.imports.cas_pdf("cas_statement.pdf", password="INVESTOR_PAN")

        # Generate Realized Capital Gains for Financial Year 2025-26
        gains = await client.capital_gains.get(investor_id=1, fy="2025-26")

        print(f"=== Capital Gains Report (FY {gains.fy}) ===")
        print(f"Realized Long-Term Gains (LTCG):  INR {gains.ltcg_total:,.2f}")
        print(f"Realized Short-Term Gains (STCG): INR {gains.stcg_total:,.2f}\n")

        print("Disposal Lots Breakdown (Schedule 112A):")
        for row in gains.rows:
            print(
                f"- {row.security_name} | Sold: {row.sell_date} | "
                f"Units: {row.units:,.3f} | Sell Price: ₹{row.sell_price:,.2f} | "
                f"Cost: ₹{row.cost_basis:,.2f} | Gain: ₹{row.gain_inr:,.2f} ({row.gain_type})"
            )


if __name__ == "__main__":
    asyncio.run(generate_tax_report())
```

---

## 2. Private & Self-Hosted Personal Net Worth Tracker

### Target Audience
Privacy-focused investors who refuse to upload their financial statements or PAN passwords to cloud-hosted wealth platforms.

### The Problem
Commercial wealth trackers store plaintext statements, portfolio values, and identity details on centralized servers, creating privacy risks.

### Solution with `folioman-client`
* Runs **100% locally** on your machine using an embedded SQLite database.
* Plaintext PAN is never stored unencrypted; it is hashed with **HMAC-SHA256** for blind indexing and encrypted with **AES-256-GCM**.
* Automatically backfills multi-year NAV curves from open public archives (`captnemo` and `mfapi.in`) without tracking user identities.

```python
import asyncio
from folioman_client import FoliomanClient


async def private_portfolio_tracker():
    # Database lives in a local folder with SQLite WAL mode enabled
    async with FoliomanClient(database_url="sqlite:///./my_private_portfolio.db") as client:
        # 1. Ingest CAMS/KFintech statement
        await client.imports.cas_pdf("cas_oct_2026.pdf", password="MY_PAN_PASSWORD")

        # 2. Backfill historical NAVs
        await client.navs.backfill()

        # 3. View net worth and annualized money-weighted return (XIRR)
        summary = await client.portfolio.get(investor_id=1)
        print(f"Total Net Worth: INR {summary.total_inr:,.2f}")
        print(f"Portfolio XIRR:  {summary.xirr:.2%}" if summary.xirr else "XIRR: N/A")

        # 4. View asset allocation breakdown
        print("\nAsset Mix Allocation:")
        for mix in summary.asset_mix:
            print(f"- {mix.security_type}: INR {mix.value_inr:,.2f}")


if __name__ == "__main__":
    asyncio.run(private_portfolio_tracker())
```

---

## 3. Multi-Client Family Office & RIA Advisor Backend

### Target Audience
SEBI-Registered Investment Advisors (RIAs), Family Offices, and wealth management SaaS builders.

### The Problem
Advisors manage hundreds of investors grouped into family entities, requiring multi-tenant separation, unified family net worth rollups, and AMC exposure monitoring.

### Solution with `folioman-client`
Folioman provides native `Family` groupings, allows connecting to a scalable **PostgreSQL** cluster, and provides instant risk concentration analytics (AMC and category weights).

```python
import asyncio
from folioman_client import FoliomanClient


async def advisor_portal():
    # Connect to enterprise PostgreSQL instance
    db_url = "postgresql+psycopg://advisor_app:secure_pass@localhost:5432/wealth_prod"
    async with FoliomanClient(database_url=db_url) as client:
        # Create or fetch clients
        client_a = await client.investors.create("Arun Sharma", pan="ABCDE1234F", family_id=101)
        client_b = await client.investors.create("Priya Sharma", pan="FGHIJ5678K", family_id=101)

        # Ingest statements for family members
        await client.imports.cas_pdf("arun_cas.pdf", password="ABCDE1234F", investor_id=client_a.id)
        await client.imports.cas_pdf("priya_cas.pdf", password="FGHIJ5678K", investor_id=client_b.id)

        # Refresh price feeds
        await client.navs.refresh()

        # Evaluate risk concentration across fund houses
        summary = await client.portfolio.get(investor_id=client_a.id)
        print(f"Investor: {client_a.name} | Total Value: INR {summary.total_inr:,.2f}\n")
        print("Fund House (AMC) Exposure:")
        for amc in summary.amc_mix:
            print(f"  - {amc.label:<30} INR {amc.value_inr:>12,.2f}")


if __name__ == "__main__":
    asyncio.run(advisor_portal())
```

---

## 4. Demat Tradebook vs. Statement Reconciliation & Audit

### Target Audience
Stock market traders, demat auditors, and portfolio managers verifying broker accuracy.

### The Problem
Discrepancies frequently occur between broker tradebooks (buy/sell executions) and depository statements (NSDL/CDSL holding balances) due to off-market transfers, unpaid delivery shares, bonus issues, or corporate action delays.

### Solution with `folioman-client`
Folioman combines NSDL/CDSL eCAS statements with trade transactions and runs automated reconciliation:
$$\Delta = \text{net\_units\_from\_trades} - \text{statement\_units}$$

```python
import asyncio
from datetime import date
from decimal import Decimal
from folioman_client import FoliomanClient


async def audit_demat_account():
    async with FoliomanClient() as client:
        # 1. Ingest official NSDL / CDSL eCAS PDF
        await client.imports.cas_pdf("nsdl_ecas.pdf", password="MY_DEMAT_PASS")

        # 2. Record individual tradebook executions (or import broker tradebook CSV)
        await client.transactions.create(
            investor_id=1,
            security_id=15,  # Reliance Industries
            date=date(2025, 4, 15),
            transaction_type="BUY",
            units=Decimal("100"),
            nav_or_price=Decimal("2800.00"),
            amount=Decimal("280000.00"),
        )

        # 3. Check reconciliation & integrity status
        statuses = await client.reconciliation.get_statuses(investor_id=1)
        for s in statuses:
            print(f"Security: {s['security_name']}")
            print(f"  - Integrity Status: {s['status']}")  # MATCH, MISMATCH, SNAPSHOT_ONLY
            print(f"  - Trade Ledger Units: {s['ledger_units']}")
            print(f"  - Demat Holding Units: {s['holding_units']}")
            print(f"  - Tax Safe: {s['tax_safe']}\n")


if __name__ == "__main__":
    asyncio.run(audit_demat_account())
```

---

## 5. Automated Daily Portfolio Valuation & NAV Scheduler

### Target Audience
Developers building personal portfolio notification bots (Telegram, Discord, Slack) or automated morning/evening valuation sync scripts.

### The Problem
NAV prices update every evening between 9:00 PM and 11:00 PM IST on AMFI and NSE. Investors want automated scheduled refreshes with daily P&L and day-change notifications.

### Solution with `folioman-client`
Folioman includes a built-in background scheduler (`FoliomanScheduler`) and day-change calculations:

```python
import asyncio
from folioman_client import FoliomanClient


async def daily_valuation_bot():
    async with FoliomanClient() as client:
        # 1. Fetch latest closing NAVs & stock prices
        refresh_stat = await client.navs.refresh()
        print(f"Updated {refresh_stat['updated']} price points.")

        # 2. Query today's portfolio summary
        summary = await client.portfolio.get(investor_id=1)

        print("\n=== Daily Portfolio Report ===")
        print(f"Current Value: INR {summary.total_inr:,.2f}")
        print(f"Day Change:    INR {summary.day_change_inr:,.2f} ({summary.day_change_pct:.2%})" 
              if summary.day_change_inr else "Day Change: N/A")

        print("\nTop Holdings Today:")
        holdings = await client.holdings.list(investor_id=1)
        for h in holdings[:5]:
            val = f"INR {h.value_inr:,.2f}" if h.value_inr is not None else "Unpriced"
            day_chg = f"{h.day_change_pct:+.2%}" if h.day_change_pct is not None else "0.00%"
            print(f"  - {h.name[:30]:<30} | {val:>15} | 1D: {day_chg}")


if __name__ == "__main__":
    asyncio.run(daily_valuation_bot())
```

---

## 6. Multi-Asset Global Portfolio (Mutual Funds + US Stocks + Crypto)

### Target Audience
Modern investors with diversified wealth across Indian mutual funds, Indian equities, US tech stocks, Sovereign Gold Bonds, and cryptocurrencies.

### The Problem
Traditional Indian portfolio trackers only handle mutual funds or Indian equities, ignoring foreign holdings (USD conversion) and digital assets.

### Solution with `folioman-client`
Folioman provides a unified multi-asset engine that aggregates domestic mutual funds, NASDAQ/NYSE equities (with automated USD $\rightarrow$ INR conversion via `fx_rates`), and cryptocurrencies (via CoinGecko), computing a **single consolidated XIRR**.

```python
import asyncio
from decimal import Decimal
from datetime import date
from folioman_client import FoliomanClient


async def global_wealth_overview():
    async with FoliomanClient() as client:
        # Ingest Indian Mutual Funds via CAS PDF
        await client.imports.cas_pdf("cams_cas.pdf", password="MY_PAN_PASS")

        # Update market price feeds across all assets:
        # - Domestic mutual funds -> AMFI / Captnemo
        # - Equities & ETFs -> NSE Bhavcopy
        # - US Equities -> Yahoo Finance & FX conversion
        # - Crypto -> CoinGecko API
        await client.navs.refresh()

        # Build full multi-asset summary
        summary = await client.portfolio.get(investor_id=1)

        print("=== Consolidated Global Portfolio ===")
        print(f"Total Net Worth (INR): ₹{summary.total_inr:,.2f}")
        print(f"Consolidated XIRR:     {summary.xirr:.2%}\n")

        print("Macro Asset Allocation (Category Mix):")
        for cat in summary.category_mix:
            pct = (cat.value_inr / summary.total_inr) * 100 if summary.total_inr else 0
            print(f"  - {cat.label:<15} ₹{cat.value_inr:>14,.2f} ({pct:>5.1f}%)")


if __name__ == "__main__":
    asyncio.run(global_wealth_overview())
```

---

## Command Line Interface (CLI) Quick Reference

Any of these operations can also be executed directly from your terminal using the bundled `folioman` CLI:

```bash
# 1. Ingest statement
folioman import cas /path/to/cas.pdf --password "MY_PAN"

# 2. Backfill historical NAV curves
folioman navs backfill

# 3. View active holdings
folioman holdings list -i 1

# 4. Generate Schedule 112A capital gains report
folioman capital-gains report -i 1 --fy "2025-26"

# 5. Query portfolio valuation
folioman portfolio summary -i 1
```
