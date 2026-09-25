# Practical Examples & Recipes

This page provides practical, copy-pasteable examples for common tasks with `folioman-client`.

---

## 1. Quickstart with Environment Variables

Set your environment variables:

```bash
export FOLIOMAN_BASE_URL="http://localhost:8000"
export FOLIOMAN_USERNAME="advisor_demo"
export FOLIOMAN_PASSWORD="secretpassword"
```

Run script:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investors = await client.investors.list()
        print(f"Total investors found: {len(investors)}")
        for inv in investors:
            print(f"- {inv.name} (ID: {inv.id})")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 2. Querying Portfolio Summaries & Holdings

Retrieve full portfolio metrics, asset mix, and underlying holdings for an investor:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investor_id = 1
        summary = await client.portfolio.get(investor_id)

        print(f"=== Portfolio for Investor #{summary.investor_id} ===")
        print(f"As of: {summary.as_of}")
        print(f"Total Value: INR {summary.total_inr:,.2f}")
        print(f"Day Change: INR {summary.day_change_inr} " if summary.day_change_inr else "")
        print(f"XIRR: {summary.xirr * 100:.2f}%" if summary.xirr is not None else "XIRR: N/A")

        print("\n--- Asset Allocation Mix ---")
        for mix in summary.asset_mix:
            print(f"{mix.security_type.upper():<12} : INR {mix.value_inr:>12,.2f}")

        print("\n--- Priced Holdings ---")
        for holding in summary.holdings:
            print(
                f"{holding.name:<30} | Units: {holding.units:>10} | Value: INR {holding.value_inr}"
            )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 3. Scheme Detail and Historical NAV Curves

Drill down into a specific scheme holding to inspect historical NAV points and folio breakdown:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investor_id = 1
        security_id = 10  # Scheme ID

        scheme = await client.holdings.get(investor_id, security_id)

        print(f"Scheme: {scheme.security.name}")
        print(f"ISIN: {scheme.security.isin} | Category: {scheme.security.category}")
        print(f"Total Units: {scheme.units} | Value: INR {scheme.value_inr}")

        print(f"\nHistorical NAV Points (Total {len(scheme.nav_history)}):")
        for pt in scheme.nav_history[-5:]:
            print(f"  {pt.date}: NAV {pt.nav}")

        print(f"\nFolios ({len(scheme.folios)}):")
        for folio in scheme.folios:
            print(f"  Folio #{folio.number}: {folio.units} units ({folio.broker})")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Historical Net Worth Valuation Series

Reconstruct an investor's historical net worth time series across monthly intervals:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investor_id = 1

        series = await client.valuations.list(
            investor_id,
            from_date="2025-01-01",
            to_date="2026-01-01",
            granularity="monthly",
        )

        print(f"Valuation Series from {series.start} to {series.end}")
        for pt in series.points:
            gain = pt.value_inr - pt.invested_inr
            print(
                f"{pt.date} | Value: INR {pt.value_inr:>12,.2f} | "
                f"Cost: INR {pt.invested_inr:>12,.2f} | Unrealized Gain: INR {gain:>12,.2f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Tax Capital Gains Reporting

Fetch realized capital gains reports for tax filing:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investor_id = 1

        # Summary across all financial years
        fy_summaries = await client.capital_gains.list(investor_id)
        print("Capital Gains by Financial Year:")
        for pt in fy_summaries:
            print(f"  FY {pt.fy} -> STCG: INR {pt.stcg:,.2f} | LTCG: INR {pt.ltcg:,.2f}")

        # Detailed report for a specific financial year
        target_fy = "2024-25"
        report = await client.capital_gains.get(investor_id, fy=target_fy)
        print(f"\nDetailed Gains for {report.fy}:")
        print(f"Total STCG: INR {report.stcg_total:,.2f}")
        print(f"Total LTCG: INR {report.ltcg_total:,.2f}")

        for row in report.rows:
            print(
                f" - {row.sold_on} | {row.name} ({row.term}) | "
                f"Proceeds: INR {row.sale_value} | Cost: INR {row.cost} | Gain: INR {row.gain}"
            )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Concurrent Investor Fetching with `asyncio.gather`

Execute multiple async operations concurrently with shared connection pooling and single-flight token authentication:

```python
import asyncio
from folioman_client import FoliomanClient, PortfolioSummary


async def get_summary_safe(client: FoliomanClient, investor_id: int) -> PortfolioSummary | None:
    try:
        return await client.portfolio.get(investor_id)
    except Exception as exc:
        print(f"Failed to fetch portfolio for investor {investor_id}: {exc}")
        return None


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investors = await client.investors.list()
        investor_ids = [inv.id for inv in investors]

        # Fetch portfolios concurrently
        tasks = [get_summary_safe(client, inv_id) for inv_id in investor_ids]
        summaries = await asyncio.gather(*tasks)

        valid_summaries = [s for s in summaries if s is not None]
        total_aum = sum(s.total_inr for s in valid_summaries)
        print(f"Total Assets Under Management across {len(valid_summaries)} investors: INR {total_aum:,.2f}")


if __name__ == "__main__":
    asyncio.run(main())
```
