import asyncio
import os
from folioman_client import FoliomanClient
from dotenv import load_dotenv

load_dotenv()


async def main():
    # Minimum setup; Default to local sqlite database.
    # Replace the URL with your database url.
    async with FoliomanClient(
        database_url="sqlite:///./.cache/folioman-example.db"
    ) as client:
        print("Importing cas file")
        job = await client.imports.cas_pdf(
            os.getenv("CAS_FILE_PATH"), os.getenv("CAS_FILE_PASS")
        )
        print(f"filename : {job['file']}")
        print(f"Schemes : {job['schemes']}")

        print("\n\nChecking navs freshness")
        freshness = await client.navs.freshness()
        print(f"Last refresh {freshness['last_refreshed_at']}")
        print(f"Next scheduled refresh {freshness['next_refresh_at']}")

        print("\n\n Backfilling navs")
        await client.navs.backfill()

        print("\n\nPortfolio Summary")
        summary = await client.portfolio.get(investor_id=1)
        # BUG total value is coming as 0 for all holding
        print(f"Total value : {summary.total_inr:,.2f}")

        holdings = await client.holdings.list(investor_id=1)
        for h in holdings:
            val_str = (
                f"INR {h.value_inr:,.2f}" if h.value_inr is not None else "Unpriced"
            )
            xirr_str = f"{h.xirr:.2%}" if h.xirr is not None else "N/A"
            print(f"- {h.name}: {h.units} units | Value: {val_str} | XIRR: {xirr_str}")
        # 4. Generate Realized Capital Gains Report (Schedule 112A)
        gains = await client.capital_gains.get(investor_id=1, fy="2025-26")
        print(f"FY 2025-26 Realized LTCG: INR {gains.ltcg_total:,.2f}")
        print(f"FY 2025-26 Realized STCG: INR {gains.stcg_total:,.2f}")
    return


if __name__ == "__main__":
    asyncio.run(main())
