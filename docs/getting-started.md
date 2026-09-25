# Getting Started

This guide walks you through installing `folioman-client`, configuring credentials, instantiating the asynchronous client, and executing your first API requests.

---

## 1. Installation

### Using pip

```bash
pip install folioman-client
```

### Using uv

If you are using Astral's `uv`:

```bash
uv add folioman-client
```

### From Source

For development or bleeding-edge features:

```bash
git clone https://github.com/sid-146/folioman-client.git
cd folioman-client
uv sync
```

---

## 2. Basic Client Creation

`FoliomanClient` offers three primary ways to initialize connection settings:

### Explicit Arguments

Pass configuration directly when creating the instance:

```python
from folioman_client import FoliomanClient

client = FoliomanClient(
    base_url="http://localhost:8000",
    username="advisor_1",
    password="supersecretpassword",
    timeout=30.0,
)
```

### From `FoliomanSettings`

Configure using strongly typed Pydantic settings:

```python
from folioman_client import FoliomanClient, FoliomanSettings

settings = FoliomanSettings(
    base_url="https://api.folioman.internal",
    username="advisor_1",
    password="supersecretpassword",
    timeout=45.0,
)
client = FoliomanClient.from_settings(settings)
```

### From Environment Variables (`from_env`)

Automatically detect credentials from system environment variables or a local `.env` file:

```python
from folioman_client import FoliomanClient

client = FoliomanClient.from_env()
```

---

## 3. Asynchronous Context Manager Usage

We strongly recommend using `FoliomanClient` inside an `async with` block. The context manager guarantees that the underlying `httpx.AsyncClient` transport and its connection pools are cleanly closed when execution exits:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    async with FoliomanClient.from_env() as client:
        investors = await client.investors.list()
        print(f"Found {len(investors)} accessible investors.")


if __name__ == "__main__":
    asyncio.run(main())
```

If you manage the client manually without a context manager, ensure you invoke `await client.close()` in a `finally` block:

```python
client = FoliomanClient.from_env()
try:
    investors = await client.investors.list()
finally:
    await client.close()
```

---

## 4. Making Your First API Request

Here is a complete, executable script that connects to the Folioman service, lists investors, fetches a detailed profile, and retrieves an investor's portfolio valuation:

```python
import asyncio
from folioman_client import (
    FoliomanClient,
    FoliomanNotFoundError,
    FoliomanAuthError,
    FoliomanAPIError,
)


async def main() -> None:
    async with FoliomanClient(
        base_url="http://localhost:8000",
        username="advisor",
        password="password123",
    ) as client:
        try:
            # 1. List accessible investors
            investors = await client.investors.list()
            if not investors:
                print("No investors found.")
                return

            first_investor = investors[0]
            print(f"Primary Investor: {first_investor.name} (ID: {first_investor.id})")

            # 2. Fetch detailed profile with masked PAN
            detail = await client.investors.get(first_investor.id)
            print(f"PAN: {detail.pan_masked} | Email: {detail.email}")

            # 3. Retrieve portfolio summary
            summary = await client.portfolio.get(first_investor.id)
            print(f"Portfolio Total: INR {summary.total_inr:,.2f}")
            print(f"XIRR: {summary.xirr * 100:.2f}%" if summary.xirr else "XIRR: N/A")

            # 4. Inspect holdings
            print("\nTop Holdings:")
            for holding in summary.holdings[:5]:
                print(f" - {holding.name} ({holding.security_type}): INR {holding.value_inr}")

        except FoliomanAuthError as err:
            print(f"Authentication failed: {err}")
        except FoliomanNotFoundError as err:
            print(f"Requested resource not found: {err}")
        except FoliomanAPIError as err:
            print(f"Folioman API returned error [{err.status_code}]: {err.response_data}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Next Steps

- Explore [Configuration](configuration.md) to set up `.env` files and production overrides.
- Learn about [Authentication](authentication.md) and automated token refresh mechanics.
- Inspect the [Client Resource Reference](client.md) to see all methods available on `client.portfolio`, `client.holdings`, `client.transactions`, `client.valuations`, and `client.capital_gains`.
