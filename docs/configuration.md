# Configuration

`folioman-client` uses Pydantic's `pydantic-settings` to manage configuration backed by environment variables and `.env` files.

---

## The `FoliomanSettings` Class

The configuration object is defined in `folioman_client.config.FoliomanSettings`. All settings use the `FOLIOMAN_` environment variable prefix.

```python
from folioman_client import FoliomanSettings

settings = FoliomanSettings()
```

### Settings Schema & Defaults

| Setting Attribute | Environment Variable | Type    | Default Value             | Description                                                   |
| :---------------- | :------------------- | :------ | :------------------------ | :------------------------------------------------------------ |
| `base_url`        | `FOLIOMAN_BASE_URL`  | `str`   | `"http://localhost:8000"` | Root URL of the Folioman REST API service.                    |
| `username`        | `FOLIOMAN_USERNAME`  | `str`   | `""`                      | Advisor username or client identifier for JWT authentication. |
| `password`        | `FOLIOMAN_PASSWORD`  | `str`   | `""`                      | User password or secret credentials for JWT authentication.   |
| `timeout`         | `FOLIOMAN_TIMEOUT`   | `float` | `30.0`                    | Default timeout in seconds applied to HTTP requests.          |

### Helper Properties

For backwards-compatibility and convenience, `FoliomanSettings` also exposes the following aliases:

- `settings.folioman_url` -> returns `settings.base_url`
- `settings.folioman_username` -> returns `settings.username`
- `settings.folioman_password` -> returns `settings.password`

---

## Environment Variables and `.env` Files

`FoliomanSettings` automatically parses `.env` files in your working directory.

### Example `.env` Configuration

```dotenv
# Folioman API Service Endpoint
FOLIOMAN_BASE_URL=http://localhost:8000

# Advisor Credentials
FOLIOMAN_USERNAME=advisor@firm.com
FOLIOMAN_PASSWORD=correct-horse-battery-staple

# Request Timeout (seconds)
FOLIOMAN_TIMEOUT=45.0
```

> [!WARNING]
> **Never commit your `.env` files or hardcode passwords in version control.**
> Add `.env` to your `.gitignore` file immediately. For containerized deployments (Docker, Kubernetes), supply configuration using environment secrets or secrets managers (e.g. AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault).

---

## Loading and Overriding Configuration

### 1. Default Global Settings (`settings`)

A default pre-instantiated singleton is available via `folioman_client.settings`:

```python
from folioman_client import settings

print(settings.base_url)
print(settings.timeout)
```

### 2. Loading via `from_env()`

When initializing the client with `FoliomanClient.from_env()`, a fresh `FoliomanSettings()` instance is created reading current process environment variables:

```python
from folioman_client import FoliomanClient

async with FoliomanClient.from_env() as client:
    # Uses environment variables
    investors = await client.investors.list()
```

### 3. Programmatic Overrides with `from_settings()`

You can instantiate `FoliomanSettings` programmatically with keyword arguments to override selected parameters:

```python
from folioman_client import FoliomanClient, FoliomanSettings

custom_settings = FoliomanSettings(
    base_url="https://folioman.staging.internal",
    username="service_account_staging",
    password="staging_password",
    timeout=60.0,
)

async with FoliomanClient.from_settings(custom_settings) as client:
    investors = await client.investors.list()
```

### 4. Direct Constructor Overrides

Individual settings can also be overridden directly in `FoliomanClient.__init__`:

```python
from folioman_client import FoliomanClient

# Only override timeout while reading base_url and credentials from the environment
async with FoliomanClient(timeout=10.0) as client:
    investors = await client.investors.list()
```

---

## Recommended Configurations

### Local Development

For local development against a dockerized or localhost Folioman instance:

```dotenv
FOLIOMAN_BASE_URL=http://127.0.0.1:8000
FOLIOMAN_USERNAME=dev_advisor
FOLIOMAN_PASSWORD=dev_secret
FOLIOMAN_TIMEOUT=15.0
```

### Production Workloads

For production deployments:

1. **Use TLS/HTTPS**: Set `FOLIOMAN_BASE_URL` with an `https://` prefix to protect tokens in transit.
2. **Dedicated Service Accounts**: Provision isolated advisor credentials for each background consumer or service.
3. **Appropriate Timeouts**: Adjust `FOLIOMAN_TIMEOUT` based on report complexity. Large multi-year capital gains queries or valuation series can take several seconds to compute. A timeout of `30.0` to `60.0` seconds is typical.
