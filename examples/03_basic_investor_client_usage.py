import asyncio
import os

from dotenv import load_dotenv

from folioman_client import DuplicateInvestorError, FoliomanClient

load_dotenv()


async def main():
    print("Running investor client usage...")
    async with FoliomanClient(
        database_url=os.getenv("DB_URL"), mode="embedded"
    ) as client:
        # Pass family id to list all investor from the family.
        investors = await client.investors.list()
        print("Listing all available investors.")
        for investor in investors:
            print("Investor: ", investor.name)
            print("Email: ", investor.email)
            print("Family ID: ", investor.family_id, end="\n\n")

        print("Fetching investor details using id.")
        investor = await client.investors.get(1)
        print("Investor details:")
        print("Name: ", investor.name)
        print("Email: ", investor.email)
        # Created at timestamp from database
        print("Investor Created At: ", investor.created_at, end="\n\n")

        print("Creating a new investor...")
        # Raises error if investor with same PAN already exists.
        try:
            new_investor = await client.investors.create(
                name="John Doe",
                pan="ABCD1234E",
                email="john.doe@example.com",
            )
            print("New investor created:")
            print("Name: ", new_investor.name)
            print("Email: ", new_investor.email)
            print("Family ID: ", new_investor.family_id)
        except DuplicateInvestorError as e:
            print(f"Investor already exists: {e}")
        except Exception as e:
            print(f"Error creating investor: {e}")


if __name__ == "__main__":
    asyncio.run(main())
