# Installation & Setup

`folioman-client` is an embedded portfolio engine and CLI for Indian personal finance, mutual funds, and equities. It runs on Windows, macOS, and Linux with Python 3.11+.

---

## 1. Prerequisites

- **Python Version**: `>= 3.11` (Tested on 3.11, 3.12, 3.13, and 3.14).
- **Operating System**: Windows 10/11, macOS (Intel & Apple Silicon), or Linux (x86_64, aarch64).
- **Default Database**: Zero external dependencies required. An embedded SQLite database is created automatically at `~/.folioman/folioman.db`.

---

## 2. Standard Installation

Install `folioman-client` from your terminal:

=== "uv (Recommended)"

    ```bash
    uv add folioman-client
    ```

=== "pip"

    ```bash
    pip install folioman-client
    ```

=== "poetry"

    ```bash
    poetry add folioman-client
    ```

---

## 3. Optional PostgreSQL Support

By default, Folioman operates over SQLite via `aiosqlite`. For multi-user concurrent production setups, install with the `postgres` extra to enable native `psycopg3` async driver support:

```bash
pip install "folioman-client[postgres]"
# or with uv:
uv add "folioman-client[postgres]"
```

Then configure your PostgreSQL connection URL via environment variable:
```bash
export FOLIOMAN_DATABASE_URL="postgresql+psycopg://username:password@localhost:5432/folioman_db"
```

---

## 4. Installing from Source (For Development)

To contribute to `folioman-client` or test unreleased features from GitHub:

```bash
# Clone the repository
git clone https://github.com/sid-146/folioman-client.git
cd folioman-client

# Option A: With uv (recommended)
uv sync --all-extras

# Option B: With pip & venv
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev,postgres]"
```

---

## 5. Verifying Installation

Verify that the CLI and Python SDK are correctly installed:

### Verify CLI:
```bash
folioman --version
```
*Expected output:*
```text
folioman, version 0.2.0
```

### Verify Python Import:
```bash
python -c "import folioman_client; print('Folioman version:', folioman_client.__version__)"
```

### Bootstrap Local Database:
Run the seed command to initialize SQLite tables and download reference ISIN dictionaries:
```bash
folioman isin seed
```

---

## 6. Directory Structure & Files Created

When initialized, Folioman stores local data under your user home directory:

```text
~/.folioman/
├── folioman.db         # SQLite database file (WAL mode enabled)
├── keys/
│   └── master.key      # Local Fernet AES encryption key (permissions: 0600)
└── logs/               # Diagnostic error logs
```

---

## 7. Troubleshooting Common Installation Issues

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'psycopg'` | PostgreSQL URL configured but driver not installed. | Run `pip install "folioman-client[postgres]"` |
| `UnsupportedPythonVersion: Requires >=3.11` | Active Python environment is 3.10 or older. | Upgrade Python to 3.11+ using `uv python install 3.12` or official installer. |
| `PermissionError: ~/.folioman/keys/master.key` | Restrictive OS permissions. | Ensure user has read/write permissions to user home directory (`$HOME` or `%USERPROFILE%`). |
