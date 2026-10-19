import asyncio
import os
from dotenv import load_dotenv
from folioman_client import FoliomanClient

load_dotenv()


async def main():
    print("Running folio client usage...")
    async with FoliomanClient(
        database_url=os.getenv("DB_URL"), mode="embedded"
    ) as client:
        # Fetch available investors
        investors = await client.investors.list()
        if not investors:
            print("No investors found.")
            return

        investor = investors[0]
        print(f"Listing folios for investor {investor.name} (ID: {investor.id})...")
        folios = await client.folios.list(investor.id)
        for folio in folios:
            print(
                f"Folio: {folio.number} | AMC: {folio.amc_code} | Type: {folio.folio_type}"
            )

        # Create a sample folio (returns typed Folio Pydantic model)
        print("\nCreating a sample folio...")
        try:
            new_folio = await client.folios.create(
                investor_id=investor.id,
                number="FOLIO-SAMPLE-01",
                amc_code="HDFC",
                folio_type="mf",
            )
            print(
                f"Created Folio: ID={new_folio.id}, Number={new_folio.number}, AMC={new_folio.amc_code}"
            )
        except Exception as e:
            print(f"Info/Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
