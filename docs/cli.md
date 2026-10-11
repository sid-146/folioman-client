# CLI Reference

`folioman-client` includes a comprehensive command-line interface `folioman`. It allows you to ingest statements, sync prices, manage the reference ISIN dictionary, and run portfolio reconciliations directly from your terminal.

---

## Global Options

All `folioman` commands support the following global options:

- `--db <URL>`: SQLAlchemy database URL (e.g. `postgresql+psycopg://user:pass@localhost/portfolio`). If omitted, uses the `FOLIOMAN_DATABASE_URL` environment variable or defaults to SQLite (`~/.folioman/folioman.db`).
- `--data-dir <PATH>`: Custom directory for local files and logs. Overrides `FOLIOMAN_DATA_DIR`.
- `-v, --verbose`: Enable debug logging and verbose SQL output.
- `--help`: Display help and usage information.

---

## Command Groups

### 1. `folioman isin`

Manages the national ISIN, mutual fund scheme, and grandfathering reference catalog.

```bash
# Seed reference dictionary into the database from the bundled offline dataset
folioman isin seed

# Check remote repository (casparser.atomcoder.com) and download updates
folioman isin update

# Inspect current ISIN database version and last updated timestamp
folioman isin status
```

---

### 2. `folioman import`

Ingests statement files into the selected database.

#### `folioman import cas`

Imports a CAMS, KFintech, or NSDL/CDSL eCAS PDF statement:

```bash
folioman import cas <FILE_PATH> --password <PASSWORD> [--investor-id <ID>]
```

**Options:**

- `--password, -p`: Required password to unlock the encrypted statement PDF (usually the investor's PAN).
- `--investor-id`: Optional ID of an existing investor to attach statements to. If omitted, matches or creates an investor using the PAN in the statement.

**Example:**

```bash
folioman import cas ~/Documents/CAMS_CAS.pdf -p "ABCDE1234F"
```

#### `folioman import csv`

Imports custom or broker tradebook CSV files:

```bash
folioman import csv <FILE_PATH> --investor-id <ID>
```

---

### 3. `folioman navs`

Manages market NAV and equity closing price feeds.

#### `folioman navs refresh`

Fetches the latest closing quotes for all securities currently held in active portfolios:

```bash
folioman navs refresh [--types <mf,equity,crypto>]
```

**Options:**

- `--types`: Comma-separated list of asset types to refresh (e.g. `mf,equity`). Defaults to all.

#### `folioman navs backfill`

Scans held securities for historical price gaps between their earliest trade date and today, and backfills missing NAV history:

```bash
folioman navs backfill [--force]
```

**Options:**

- `--force`: Re-pull the full historical price span regardless of existing data points.

---

### 4. `folioman symbols`

Repairs holdings and resolves trading identifiers.

#### `folioman symbols resolve`

Resolves missing NSE/BSE trading symbols for demat holdings (eCAS statements report holdings by ISIN only):

```bash
folioman symbols resolve [--backfill]
```

**Options:**

- `--backfill`: Automatically trigger price-history backfill for newly resolved symbols.

---

### 5. `folioman reconcile`

Runs balance reconciliation and integrity verification.

#### `folioman reconcile all`

Re-reconciles trade ledger units against observed statement snapshots across all folios and investors:

```bash
folioman reconcile all
```

This verifies unit balances, calculates any drift, and updates the `tax_safe` status required for capital gains reporting.

---

### 6. `folioman corporate-actions`

Fetches and caches corporate actions.

#### `folioman corporate-actions refresh`

Queries NSE/BSE feeds for recent stock splits, bonus shares, mergers, and dividends:

```bash
folioman corporate-actions refresh
```

---

### 7. `folioman valuations`

Manages portfolio net-worth series rollups.

#### `folioman valuations extend`

Rolls all active investor portfolio valuations forward to today:

```bash
folioman valuations extend
```

#### `folioman valuations process-pending`

Processes pending or failed valuation calculation tasks:

```bash
folioman valuations process-pending
```

---

### 8. `folioman scheduler`

Runs an in-process background automation daemon.

#### `folioman scheduler run`

Starts a blocking in-process scheduler (`APScheduler`) that automatically runs 6-hourly NAV refreshes, daily valuation rollups, and ISIN database update checks:

```bash
folioman scheduler run
```

---

### 9. `folioman demo`

Demo and testing utilities.

#### `folioman demo seed`

Seeds the database with realistic synthetic investors, mutual fund portfolios, equity transactions, and historical NAVs for testing and demonstration:

```bash
folioman demo seed
```
