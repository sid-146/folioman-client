# Storage & Configuration

`folioman-client` is designed to be zero-setup by default, while supporting production databases (PostgreSQL, MySQL) via standard SQLAlchemy connection strings.

Configuration is managed using Pydantic's `pydantic-settings`, reading from environment variables or a local `.env` file.

---

## The `FoliomanSettings` Class

The settings object is defined in `folioman_client.config.FoliomanSettings`. All settings use the `FOLIOMAN_` environment variable prefix.

```python
from folioman_client import FoliomanSettings

settings = FoliomanSettings()
```

### Settings Schema & Defaults

| Setting Attribute | Environment Variable    | Type    | Default Value | Description                                                                        |
| :---------------- | :---------------------- | :------ | :------------ | :--------------------------------------------------------------------------------- |
| `database_url`    | `FOLIOMAN_DATABASE_URL` | `str`   | `""`          | SQLAlchemy connection URL. If empty, defaults to SQLite under `data_dir`.          |
| `data_dir`        | `FOLIOMAN_DATA_DIR`     | `str`   | `""`          | Base directory for storage and logs. Defaults to OS user data dir (`~/.folioman`). |
| `fernet_key`      | `FOLIOMAN_FERNET_KEY`   | `str`   | `""`          | 32-byte url-safe base64 key for PAN encryption. Auto-generated if omitted.         |
| `timeout`         | `FOLIOMAN_TIMEOUT`      | `float` | `30.0`        | HTTP timeout (seconds) for external price feeds (mfapi, Yahoo, AMFI).              |
| `user_id`         | `FOLIOMAN_USER_ID`      | `str`   | `"default"`   | Multi-tenancy tenant or advisor scope identifier.                                  |
| `base_url`        | `FOLIOMAN_BASE_URL`     | `str`   | `""`          | *(Deprecated)* Legacy REST API URL. See [Backward Compatibility](compatibility.md).|
| `username`        | `FOLIOMAN_USERNAME`     | `str`   | `""`          | *(Deprecated)* Legacy API username.                                                |
| `password`        | `FOLIOMAN_PASSWORD`     | `str`   | `""`          | *(Deprecated)* Legacy API password.                                                |

---

## Database Configuration

Storage is fully pluggable via SQLAlchemy 2.0.

### 1. SQLite (Default)

If no connection string is provided, `folioman-client` automatically resolves a file path under the user data directory:

- Linux: `~/.local/share/folioman/folioman.db`
- macOS: `~/Library/Application Support/folioman/folioman.db`
- Windows: `%LOCALAPPDATA%\folioman\folioman.db`

#### SQLite Concurrency Guards

To prevent `OperationalError: database is locked` errors during concurrent operations, `folioman-client` automatically configures every SQLite connection with:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
```

Transactions are executed in `IMMEDIATE` mode to prevent read-upgrade deadlocks.

### 2. PostgreSQL (Production & Team Use)

For multi-user applications, web backends, or containerized deployments (Docker / Kubernetes), connect to PostgreSQL using `psycopg`:

```bash
export FOLIOMAN_DATABASE_URL="postgresql+psycopg://username:password@localhost:5432/portfolio"
```

In Python:

```python
from folioman_client import FoliomanClient

client = FoliomanClient(
    database_url="postgresql+psycopg://username:password@localhost:5432/portfolio"
)
```

Ensure `psycopg` is installed:

```bash
pip install "folioman-client[postgres]"
```

### 3. MySQL / MariaDB

```bash
export FOLIOMAN_DATABASE_URL="mysql+aiomysql://username:password@localhost:3306/portfolio"
```

---

## Unified Database Model

In `folioman-client` v0.2.0, **100% of data lives inside your configured database**:

1. **User Portfolios & Ledgers**: Investors, folios, transactions, holdings, partial blocks, and daily net-worth points.
2. **Market & Daily Prices**: Canonical securities, daily NAV history from AMFI / mfapi / Yahoo, and corporate action events.
3. **Reference Master**: The 100,000-row national ISIN and mutual fund scheme reference dictionary (`ref_schemes`, `ref_isins`, `ref_grandfathering_navs`).

This architecture ensures:

- **Stateless Applications**: You can spin up multiple containers or serverless workers pointing to a single RDS/PostgreSQL instance without needing shared persistent disk volumes.
- **Single Backup**: A single `pg_dump` backup captures your entire portfolio and reference state.

---

## Schema Initialization & Versioning

`folioman-client` handles database creation and upgrades automatically.

When `FoliomanClient()` initializes or when running `folioman isin seed`:

1. It executes `Base.metadata.create_all()` to ensure all 18 tables exist.
2. It inspects the `_schema_version` table.
3. If an older version is detected, it automatically executes non-destructive schema migrations.

---

## Sensitive Data & PAN Encryption

Under Indian data privacy guidelines, Permanent Account Numbers (PAN) must be protected.

- **Encryption at Rest**: PANs are stored encrypted using symmetric Fernet encryption (`cryptography`).
- **Deterministic Lookup**: An HMAC-SHA256 hash (`pan_hash`) is generated using the encryption key, allowing statements to match existing investors without decrypting all rows.
- **Key Resolution**:
    1. `FOLIOMAN_FERNET_KEY` environment variable.
    2. Auto-generated file (`~/.folioman/fernet.key`) created with restricted owner permissions (`0600`).
