# folioman-client

[![PyPI version](https://img.shields.io/pypi/v/folioman-client.svg)](https://pypi.org/project/folioman-client/)
[![Python versions](https://img.shields.io/pypi/pyversions/folioman-client.svg)](https://pypi.org/project/folioman-client/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation](https://img.shields.io/badge/docs-GitHub_Pages-blue.svg)](https://sid-146.github.io/folioman-client/)

Official typed asynchronous Python SDK for the **Folioman REST API**.

The `folioman-client` library provides an asynchronous, strongly typed interface for interacting with Folioman services. It handles HTTP communication, JWT authentication lifecycles, proactive and reactive token refresh, concurrent locking, and response mapping into Pydantic models.

---

## Key Features

- **Asynchronous Transport**: Built on top of `httpx.AsyncClient` with native HTTP/2 and connection pooling.
- **Automated JWT Lifecycle**: Obtains initial tokens from `/api/auth/token/pair`, automatically refreshes via `/api/auth/token/refresh`, and transparently retries requests on HTTP 401.
- **Concurrency-Safe Token Refresh**: Utilizes an internal `asyncio.Lock` to guarantee that only one concurrent refresh request runs at any time.
- **Proactive Expiry Absorption**: Evaluates token expiry using an embedded payload decoder and proactively refreshes 30 seconds before actual token expiration (`EXP_SKEW_SECONDS = 30`).
- **Typed Response Parsing**: Parses JSON payloads into Pydantic v2 models that handle `Decimal` serializations and ignore unknown extra attributes for forward-compatibility.
- **Structured Exception Hierarchy**: Maps HTTP status codes into specific client exceptions (`FoliomanAuthError`, `FoliomanNotFoundError`, `FoliomanAPIError`).

---

## Installation

```bash
pip install folioman-client
```

Or using `uv`:

```bash
uv add folioman-client
```

---

## Quickstart

It is strongly recommended to use `FoliomanClient` as an asynchronous context manager:

```python
import asyncio
from folioman_client import FoliomanClient


async def main() -> None:
    # Uses FOLIOMAN_BASE_URL, FOLIOMAN_USERNAME, FOLIOMAN_PASSWORD from environment
    async with FoliomanClient.from_env() as client:
        # Fetch accessible investors
        investors = await client.investors.list()
        for investor in investors:
            print(f"Investor: {investor.name} (ID: {investor.id})")

            # Fetch portfolio summary
            summary = await client.portfolio.get(investor.id)
            print(f"  Total Portfolio Value: INR {summary.total_inr:,.2f}")
            print(f"  XIRR: {summary.xirr * 100:.2f}%" if summary.xirr else "  XIRR: N/A")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Client Initialization

The client can be instantiated in three ways:

### 1. From Environment Variables (`from_env`)

Automatically loads configuration from environment variables or `.env` file using the `FOLIOMAN_` prefix:

```python
from folioman_client import FoliomanClient

client = FoliomanClient.from_env()
```

Supported environment variables:

- `FOLIOMAN_BASE_URL`: API service endpoint (default: `http://localhost:8000`)
- `FOLIOMAN_USERNAME`: Advisor username
- `FOLIOMAN_PASSWORD`: Advisor password
- `FOLIOMAN_TIMEOUT`: Request timeout in seconds (default: `30.0`)

### 2. Directly with Arguments

```python
from folioman_client import FoliomanClient

client = FoliomanClient(
    base_url="http://localhost:8000",
    username="advisor",
    password="supersecretpassword",
    timeout=30.0,
)
```

### 3. From a `FoliomanSettings` Instance

```python
from folioman_client import FoliomanClient, FoliomanSettings

settings = FoliomanSettings(
    base_url="http://localhost:8000",
    username="advisor",
    password="supersecretpassword",
)
client = FoliomanClient.from_settings(settings)
```

---

## Resource Sub-Clients

`FoliomanClient` exposes its API through organized resource sub-clients:

| Resource               | Methods                                              | Description                                                                      |
| :--------------------- | :--------------------------------------------------- | :------------------------------------------------------------------------------- |
| `client.investors`     | `list()`, `get(investor_id)`                         | Query advisor-accessible investors and detailed profiles with masked PAN.        |
| `client.portfolio`     | `get(investor_id, as_of=None)`                       | Query aggregated portfolio summaries, metrics, XIRR, and asset mix.              |
| `client.holdings`      | `list(investor_id)`, `get(investor_id, security_id)` | Query priced holdings, folio breakdown, historical NAV points, and transactions. |
| `client.transactions`  | `list(investor_id)`                                  | Access raw transaction ledger records (buys, sells, switches, dividends).        |
| `client.valuations`    | `list(investor_id)`, `status(investor_id)`           | Reconstruct historical net-worth time series and check calculation readiness.    |
| `client.capital_gains` | `list(investor_id)`, `get(investor_id, fy=...)`      | Generate realized STCG/LTCG capital gains reports across financial years.        |

---

## Error Handling

All client exceptions derive from `FoliomanError`:

```python
from folioman_client import (
    FoliomanClient,
    FoliomanAuthError,
    FoliomanNotFoundError,
    FoliomanAPIError,
)

async with FoliomanClient.from_env() as client:
    try:
        investor = await client.investors.get(99999)
    except FoliomanNotFoundError:
        print("Investor does not exist.")
    except FoliomanAuthError as exc:
        print(f"Authentication failed: {exc}")
    except FoliomanAPIError as exc:
        print(f"Status Code: {exc.status_code}")
        print(f"Error Details: {exc.response_data}")
```

---

## Documentation

Full documentation is available at:
**[https://sid-146.github.io/folioman-client/](https://sid-146.github.io/folioman-client/)**

To build documentation locally:

```bash
uv sync --group dev
uv run mkdocs serve
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
