# CLI Reference

`folioman-client` includes a comprehensive command-line interface `folioman`. It allows you to ingest statements, sync prices, manage the reference ISIN dictionary, and run portfolio reconciliations directly from your terminal.

---

## Global Options

All `folioman` commands support the following global options:

- `--database-url <URL>`: SQLAlchemy database URL (e.g. `postgresql+psycopg://user:pass@localhost/portfolio`). If omitted, uses the `FOLIOMAN_DATABASE_URL` environment variable or defaults to SQLite (`~/.folioman/folioman.db`).
- `--help`: Display help and usage information.
- `--version`: Display `folioman` version.

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
folioman reconcile all [--investor-id <ID>]
```

This verifies unit balances, calculates any drift, and updates the `tax_safe` status required for capital gains reporting.

#### `folioman reconcile acknowledge` / `clear`

```bash
folioman reconcile acknowledge --investor-id <ID> --security-id <SID> --folio-id <FID>
folioman reconcile clear --investor-id <ID> --security-id <SID> --folio-id <FID>
```

---

### 6. `folioman corporate-actions`

Fetches and caches corporate actions.

#### `folioman corporate-actions refresh`

Queries NSE/BSE feeds for recent stock splits, bonus shares, mergers, and dividends:

```bash
folioman corporate-actions refresh [--since-year 2020]
```

---

### 7. `folioman portfolio`

Queries portfolio summaries, metrics, and asset mix.

#### `folioman portfolio summary`

```bash
folioman portfolio summary --investor-id <ID> [--as-of YYYY-MM-DD]
```

Prints total valuation, day change, XIRR, tax-ready folio counts, asset allocation breakdown, and trailing period returns.

---

### 8. `folioman valuations`

Manages daily valuation series, coverage checks, and background ticks.

#### `folioman valuations status`

```bash
folioman valuations status --investor-id <ID>
folioman valuations status --family-id <ID>
```

#### `folioman valuations series`

```bash
folioman valuations series --investor-id <ID> [--granularity daily|weekly|monthly] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

#### `folioman valuations tick`

```bash
# Process pending recomputations
folioman valuations tick --pending

# Enqueue daily valuation extensions
folioman valuations tick --extend
```

---

### 9. `folioman capital-gains`

Realized capital gains (STCG/LTCG) and official Schedule 112A reports.

#### `folioman capital-gains list`

```bash
folioman capital-gains list --investor-id <ID> [--include-unreconciled]
```

Lists realized STCG and LTCG across each financial year.

#### `folioman capital-gains report`

```bash
folioman capital-gains report --investor-id <ID> --fy "2024-25" [--csv schedule112a.csv] [--include-unreconciled]
```

Generates lot-level capital gains report with Section 112A grandfathering, and optionally exports official 15-column Schedule 112A CSV.

---

### 10. `folioman investors`, `folios`, `transactions`, `holdings`

Entity management subcommands:

```bash
# Investors
folioman investors list
folioman investors get --investor-id <ID>
folioman investors create --name "Investor Name" [--pan "ABCDE1234F"] [--email "user@example.com"]

# Folios
folioman folios list --investor-id <ID>
folioman folios create --investor-id <ID> --number "FOLIO101" [--amc-code "HDFC"]

# Transactions
folioman transactions list --investor-id <ID> [--security-id <SID>]

# Holdings
folioman holdings list --investor-id <ID>
```

---

### 11. `folioman scheduler`

Runs an in-process background automation daemon.

#### `folioman scheduler run`

Starts a blocking in-process scheduler (`APScheduler`) that automatically runs 6-hourly NAV refreshes, daily valuation rollups, and ISIN database update checks:

```bash
folioman scheduler run
```
