# Practical Examples & Recipes

This page provides practical, copy-pasteable recipes for common workflows using `folioman-client`.

---

## 1. Complete End-to-End Ingestion & Portfolio Valuation

This script initializes the local database, ingests a CAMS/KFintech CAS statement, updates market prices, and prints portfolio metrics:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient() as client:
        # Step 1: Ingest statement PDF
        print("Parsing CAS statement...")
        job = await client.imports.cas_pdf(
            file_path="CAMS_CAS_Jan2026.pdf",
            password="ABCDE1234F",
        )
        print(f"Transactions created: {job.result.get('transactions_created')}")

        # Step 2: Fetch latest NAVs and prices
        print("Updating market prices...")
        await client.navs.refresh()

        # Step 3: Print portfolio valuation
        summary = await client.portfolio.get(investor_id=1)
        print(f"\n=== Portfolio Summary as of {summary.as_of} ===")
        print(f"Total Valuation: INR {summary.total_inr:,.2f}")
        print(f"Holdings Count:  {summary.holdings_count}")
        if summary.day_change_inr is not None:
            print(f"Day Change:      INR {summary.day_change_inr:,.2f}")
        if summary.xirr is not None:
            print(f"Annual XIRR:     {summary.xirr * 100:.2f}%")

        # Step 4: Asset allocation breakdown
        print("\n--- Asset Allocation ---")
        for mix in summary.asset_mix:
            print(f"{mix.security_type.title():<12}: INR {mix.value_inr:>12,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 2. Generating Schedule 112A Realized Capital Gains (Tax Filing)

Generate a detailed lot-level report and official 15-column Schedule 112A export for the Indian Income Tax Return (ITR):

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient() as client:
        # Generate capital gains report for Financial Year 2024-25 (Apr 2024 - Mar 2025)
        report = await client.capital_gains.get(investor_id=1, fy="2024-25")

        print(f"=== Capital Gains Report for FY {report.fy} ===")
        print(f"Total Disposals: {len(report.rows)}")
        print(f"Realized STCG:   INR {report.stcg_total:,.2f}")
        print(f"Realized LTCG:   INR {report.ltcg_total:,.2f}")

        # Display Schedule 112A eligible lots
        print("\n--- Disposal Lot Details ---")
        for row in report.rows[:5]:
            gf_flag = " (!)" if row.grandfathering_unavailable else ""
            print(
                f"{row.name[:25]:<26} | Acquired: {row.acquired_on} | Sold: {row.sold_on} | "
                f"Units: {row.units:>8.3f} | Gain: INR {row.gain:>10,.2f} ({row.term.upper()}){gf_flag}"
            )

        # Export official Schedule 112A CSV format
        s112a = await client.capital_gains.schedule_112a(investor_id=1, fy="2024-25")
        print(f"\nGenerated Schedule 112A rows: {s112a['row_count']}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 3. Extracting Historical Net-Worth Time Series

Reconstruct the daily, weekly, or monthly net-worth progression of an investor:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient() as client:
        # Fetch monthly progression over the last year
        series = await client.valuations.list(
            investor_id=1,
            from_date="2025-01-01",
            to_date="2026-01-01",
            granularity="monthly",
        )

        print(f"Historical Net-Worth Points ({len(series.points)} entries):")
        for point in series.points:
            print(f"Date: {point.date} | Net Worth: INR {point.value_inr:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Multi-Tenant Setup with PostgreSQL

In a wealth advisory or multi-tenant system, use `user_id` to enforce logical multi-tenancy:

```python
import asyncio
from folioman_client import FoliomanClient

DATABASE_URL = "postgresql+psycopg://advisor:secret@localhost:5432/wealth_db"


async def main() -> None:
    # Client for Advisor A
    async with FoliomanClient(database_url=DATABASE_URL, user_id="advisor_alpha") as client_a:
        inv_a = await client_a.investors.create("Ramesh Sharma")
        print(f"Created Investor in Alpha: {inv_a.name} (ID: {inv_a.id})")

    # Client for Advisor B
    async with FoliomanClient(database_url=DATABASE_URL, user_id="advisor_beta") as client_b:
        inv_b = await client_b.investors.create("Priya Verma")
        print(f"Created Investor in Beta: {inv_b.name} (ID: {inv_b.id})")

        # Advisor B cannot see Advisor A's investors
        investors = await client_b.investors.list()
        print(f"Advisor B sees {len(investors)} investor(s).")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Automated Weekly NAV Sync with Embedded Scheduler

For persistent processes (e.g. desktop apps or long-running worker services), enable the embedded scheduler:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    # Launch with background scheduler enabled (runs daemon thread)
    async with FoliomanClient(start_scheduler=True) as client:
        print("Folioman engine running with 6-hourly background NAV sync...")
        # Keep process alive
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
```
