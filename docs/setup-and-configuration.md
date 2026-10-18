# Setup & Configuration Guide

This guide covers environment setup, database configuration (SQLite vs PostgreSQL), encryption keys, and daemon execution for `folioman-client`.

---

## 1. Installation

### 1.1 Requirements
- **Python**: `>= 3.11` (Tested on 3.11, 3.12, 3.13, 3.14).
- **C Compiler / Build Tools**: Optional (wheels available for all major platforms).
- **Operating Systems**: Linux, macOS, Windows (x86_64, ARM64).

### 1.2 Using `uv` (Recommended)
```bash
# Clone the repository
git clone https://github.com/sid-146/folioman-client.git
cd folioman-client

# Sync dependencies into local virtual environment (.venv)
uv sync --all-extras

# Activate virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
```

### 1.3 Using `pip`
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install in editable mode with development and postgres extras
pip install -e ".[dev,postgres]"
```

---

## 2. Configuration Settings & Environment Variables

`folioman-client` reads configuration from environment variables or a local `.env` file via `pydantic-settings` (`folioman_client.config.FoliomanSettings`):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `FOLIOMAN_DATABASE_URL` | `str` | `sqlite+aiosqlite:///~/.folioman/folioman.db` | SQLAlchemy 2.0 async connection string. |
| `FOLIOMAN_PAN_SECRET` | `str \| None` | `None` | 32-byte url-safe base64 Fernet key for encrypting PANs at rest. |
| `FOLIOMAN_USER_ID` | `str` | `"default"` | Multi-tenant tenant/advisor scope identifier. |
| `FOLIOMAN_LOG_LEVEL` | `str` | `"INFO"` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `FOLIOMAN_HTTP_TIMEOUT` | `float` | `30.0` | HTTP request timeout in seconds for market data feeds. |
| `FOLIOMAN_RUN_SCHEDULER`| `bool` | `False` | Launch background APScheduler automatically inside SDK client. |
| `FOLIOMAN_DEBUG_DB_ERRORS` | `bool / int` | `0` | Enable verbose diagnostic database error blocks on stderr. |

---

## 3. Database Engine Setup

### 3.1 Zero-Configuration SQLite (Default)
By default, `folioman-client` creates an embedded SQLite database at `~/.folioman/folioman.db`.
```ini
# .env
FOLIOMAN_DATABASE_URL=sqlite+aiosqlite:///~/.folioman/folioman.db
```
- **Concurrency**: Automatically configures Write-Ahead Logging (`PRAGMA journal_mode = WAL;`) for high concurrency between read commands and write imports.
- **Foreign Keys**: Enforces `PRAGMA foreign_keys = ON;`.

### 3.2 Production PostgreSQL (with `psycopg3`)
For multi-user server deployments or large institutional portfolios:
```ini
# .env
FOLIOMAN_DATABASE_URL=postgresql+psycopg://folioman:secret_password@localhost:5432/folioman_db
```

#### Windows Event Loop Requirement for PostgreSQL
On Windows, `psycopg3` in async mode requires Python's `SelectorEventLoop` instead of the default `ProactorEventLoop`. Configure this at application startup:
```python
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```
If this policy is missing, the centralized error reporting utility intercepts the failure and outputs corrective instructions.

---

## 4. Encryption Key Management

Plaintext Permanent Account Numbers (PANs) are encrypted at rest using Fernet symmetric cryptography.

### 4.1 Generating a Master Key
You can generate a secure Fernet key using Python:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4.2 Configuring the Master Key
Set the key in your environment or `.env` file:
```ini
FOLIOMAN_PAN_SECRET=your-secret-here=
```
If no key is configured:
1. Folioman checks the native OS Credential Locker / Keychain.
2. If absent, it checks `~/.folioman/keys/pan.key` (with permissions `0600`).
3. If still absent, it generates a key on first run and persists it securely.

---

## 5. Running the Background Scheduler

To automate daily evening NAV refreshes and valuation roll-forwards, run the scheduler daemon:

### 5.1 Interactive CLI Execution
```bash
folioman scheduler run
```

### 5.2 Systemd Service Unit (Linux)
Create `/etc/systemd/system/folioman-scheduler.service`:
```ini
[Unit]
Description=Folioman Portfolio Daily Scheduler
After=network.target

[Service]
Type=simple
User=portfolio
WorkingDirectory=/home/portfolio/folioman-client
Environment="FOLIOMAN_DATABASE_URL=postgresql+psycopg://folioman:pass@localhost:5432/folioman"
ExecStart=/home/portfolio/folioman-client/.venv/bin/folioman scheduler run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
Enable and start the service:
```bash
sudo systemctl enable --now folioman-scheduler.service
```
