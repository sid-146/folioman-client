# CLI Reference

`folioman-client` includes a comprehensive command-line interface: `folioman`. It allows you to ingest statements, sync prices, resolve demat symbols, inspect holdings, manage corporate actions, run reconciliations, and generate tax reports directly from your terminal.

---

## Global Options

All `folioman` commands support the following global options:

- `--database-url <URL>`: SQLAlchemy database connection URL (e.g., `sqlite:////path/to/portfolio.db` or `postgresql+psycopg://user:pass@localhost/portfolio`). If omitted, uses the `FOLIOMAN_DATABASE_URL` environment variable or defaults to SQLite (`~/.folioman/folioman.db`).
- `--help`: Display help and usage information.
- `--version`: Display the installed `folioman` version.

> [!TIP]
> **Global Option Placement**: In Click, global options like `--database-url` must appear **before** the subcommand name:
> ```bash
> # Correct:
> folioman --database-url sqlite:////path/to/my.db isin status
>
> # Incorrect (will report unknown option):
> folioman isin status --database-url sqlite:////path/to/my.db
> ```

---

## Command Reference

### 1. `folioman isin`

Manages the national ISIN, mutual fund scheme, and Section 112A grandfathering reference catalog.

#### `folioman isin status`
Displays the current population status of the reference catalog:

```bash
folioman isin status
```

Output includes whether the catalog is seeded, the version string, number of mutual fund schemes, national ISINs, and 31-Jan-2018 grandfathering NAV records.

#### `folioman isin seed`
Seeds the reference catalog into the active database from the bundled offline dataset (or an external SQLite file):

```bash
# Seed bundled dataset (skips if already seeded)
folioman isin seed

# Force re-seed (purges and overwrites existing reference tables)
folioman isin seed --force

# Seed from a custom casparser-isin SQLite database file
folioman isin seed --source /path/to/custom_isin.db
```

#### `folioman isin resolve`
Resolves an ISIN to its full metadata (scheme name, AMFI code, RTA, SEBI category, and grandfathering NAV):

```bash
folioman isin resolve INF209K01165
```

#### `folioman isin search`
Searches mutual fund schemes by text name, AMFI code, or ISIN:

```bash
folioman isin search "Parag Parikh Flexi Cap"
folioman isin search "122639" --limit 5
```

#### `folioman isin update`
Checks the upstream repository (`casparser.atomcoder.com`) for newer reference releases and updates the local database:

```bash
folioman isin update
```

---

### 2. `folioman import`

Ingests investment statement files into the selected database.

#### `folioman import cas`
Imports and reconciles a CAMS, KFintech, or NSDL/CDSL eCAS PDF statement:

```bash
folioman import cas <FILE_PATH> --password <PASSWORD> [--user-id <UID>] [--investor-id <ID>]
```

**Options:**

- `-p, --password`: Password for decrypting the CAS PDF (usually investor PAN in uppercase). Prompts securely if omitted.
- `-u, --user-id`: Optional user/advisor account identifier (defaults to configured `user_id`).
- `-i, --investor-id`: Optional ID of an existing investor to attach statements to. If omitted, matches or creates an investor using the PAN in the statement.

**Examples:**

```bash
# Import CAMS mutual fund statement
folioman import cas ~/Documents/CAMS_CAS.pdf -p "ABCDE1234F"

# Import NSDL/CDSL eCAS demat statement into a specific investor profile
folioman import cas ~/Documents/eCAS_CDSL.pdf -p "ABCDE1234F" -i 1
```

---

### 3. `folioman navs`

Manages mutual fund NAVs and market closing prices.

#### `folioman navs refresh`
Fetches the latest available quotes for held securities from primary sources (AMFI/mfapi for mutual funds, NSE/BSE Bhavcopy for equities):

```bash
# Refresh all held asset types
folioman navs refresh

# Refresh specific asset types only
folioman navs refresh --types "mf,equity"
```

#### `folioman navs backfill`
Scans held securities for historical price gaps between their earliest trade date and today, and fills in missing historical NAVs:

```bash
# Backfill all securities with missing history
folioman navs backfill

# Backfill a single security by ID
folioman navs backfill --security-id 42

# Force a full re-scan and overwrite of historical series
folioman navs backfill --force
```

#### `folioman navs status`
Displays NAV freshness, trading-day lag, latest recorded price date, and total data points for all held securities:

```bash
folioman navs status
```

---

### 4. `folioman symbols`

Manages exchange trading symbols for demat securities (eCAS statements report holdings by ISIN only).

#### `folioman symbols resolve`
Scans demat holdings with missing NSE/BSE ticker symbols, resolves them using the `ref_isins` catalog, and optionally backfills historical prices:

```bash
# Check for matching symbols without making changes
folioman symbols resolve --dry-run

# Match symbols and write them to the database
folioman symbols resolve

# Match symbols and immediately backfill historical prices
folioman symbols resolve --backfill

# Force full historical price backfill for all newly resolved symbols
folioman symbols resolve --backfill --force-backfill
```

---

### 5. `folioman reconcile`

Runs balance reconciliation and integrity verification between the transaction ledger and reported statement snapshots.

#### `folioman reconcile all`
Runs reconciliation across positions, calculating unit drift and updating the `tax_safe` flag required for accurate capital gains computation:

```bash
# Reconcile all investors
folioman reconcile all

# Reconcile a specific investor
folioman reconcile all --investor-id 1
```

#### `folioman reconcile acknowledge`
Manually acknowledges a reported unit mismatch for a specific position (e.g., after verifying that a minor fraction was caused by rounded fractional units):

```bash
folioman reconcile acknowledge --investor-id 1 --security-id 42 --folio-id 10
```

#### `folioman reconcile clear`
Clears a previously acknowledged mismatch, restoring the real integrity status:

```bash
folioman reconcile clear --investor-id 1 --security-id 42 --folio-id 10
```

---

### 6. `folioman corporate-actions`

Fetches, inspects, and applies corporate action events (stock splits, bonus shares, dividends).

#### `folioman corporate-actions refresh`
Fetches corporate action history for held equities from NSE/BSE announcement feeds:

```bash
# Refresh announcements since 2016 for all held equities
folioman corporate-actions refresh

# Refresh announcements since a specific year
folioman corporate-actions refresh --since-year 2020

# Refresh for a specific security ID
folioman corporate-actions refresh --security-id 15
```

#### `folioman corporate-actions list`
Inspects cached corporate action announcements matching filter criteria:

```bash
# List all cached actions
folioman corporate-actions list

# Filter by action type (bonus, split, dividend, rights)
folioman corporate-actions list --kind bonus

# Filter by trading symbol or ISIN
folioman corporate-actions list --symbol TCS
folioman corporate-actions list --isin INE467B01029
```

#### `folioman corporate-actions apply`
Applies a cached corporate action (such as a 1:1 bonus issue or 1:10 stock split) to an investor folio:

```bash
folioman corporate-actions apply --investor-id 1 --folio-id 5 --reference-id 102
```

---

### 7. `folioman portfolio`

Queries portfolio summaries, valuations, and performance metrics.

#### `folioman portfolio summary`
Prints an overall portfolio summary including valuation, day change, annualized XIRR, asset allocation, top holdings, and trailing period returns:

```bash
# Current summary
folioman portfolio summary --investor-id 1

# Historical summary as of a specific date
folioman portfolio summary --investor-id 1 --as-of 2024-03-31
```

---

### 8. `folioman valuations`

Manages daily valuation series, status checks, and background recompute ticks.

#### `folioman valuations status`
Checks valuation calculation coverage and status for an individual investor or family group:

```bash
folioman valuations status --investor-id 1
folioman valuations status --family-id 2
```

#### `folioman valuations series`
Outputs a reconstructed historical net-worth time series:

```bash
# Monthly net-worth series (default)
folioman valuations series --investor-id 1

# Daily series over a date range
folioman valuations series --investor-id 1 --granularity daily --from 2023-01-01 --to 2024-01-01

# Weekly series
folioman valuations series --investor-id 1 --granularity weekly
```

#### `folioman valuations tick`
Manually triggers valuation calculation jobs:

```bash
# Run both catch-up and pending valuation calculations
folioman valuations tick

# Process pending valuation calculations only
folioman valuations tick --pending

# Enqueue daily extension for all investors
folioman valuations tick --extend
```

---

### 9. `folioman capital-gains`

Computes realized capital gains (STCG/LTCG) and generates official Section 112A tax reports.

#### `folioman capital-gains list`
Lists realized STCG and LTCG across every financial year for an investor:

```bash
folioman capital-gains list --investor-id 1

# Include transactions from unverified/unreconciled folios
folioman capital-gains list --investor-id 1 --include-unreconciled
```

#### `folioman capital-gains report`
Generates a lot-level capital gains report with Section 112A grandfathering calculations, and optionally exports to an official 15-column Schedule 112A CSV file:

```bash
# Display summary and lot breakdown in terminal
folioman capital-gains report --investor-id 1 --fy "2024-25"

# Export official Schedule 112A CSV
folioman capital-gains report --investor-id 1 --fy "2024-25" --csv ./schedule112a_fy2425.csv
```

---

### 10. Ledger Entities (`investors`, `folios`, `transactions`, `holdings`)

#### `folioman investors`
```bash
# List all investors
folioman investors list

# Filter by family group or unaffiliated status
folioman investors list --family-id 1
folioman investors list --unaffiliated

# Create a new investor profile (PAN is encrypted at rest)
folioman investors create --name "Rahul Sharma" --pan "ABCDE1234F" --email "rahul@example.com"
folioman investors create --name "Sharma HUF" --is-huf
```

#### `folioman folios`
```bash
# List all folios and demat accounts for an investor
folioman folios list --investor-id 1

# Merge a duplicate/migrated folio into a target folio
folioman folios merge --investor-id 1 --source-id 3 --target-id 2
```

#### `folioman transactions`
```bash
# List all transactions for an investor ordered chronologically
folioman transactions list --investor-id 1

# Filter transactions by security or folio
folioman transactions list --investor-id 1 --security-id 42
folioman transactions list --investor-id 1 --folio-id 5
```

#### `folioman holdings`
```bash
# List active positions (computed from ledger units or demat snapshots)
folioman holdings list --investor-id 1
```

---

### 11. `folioman scheduler`

Runs the background automation daemon.

#### `folioman scheduler run`
Starts a blocking in-process scheduler (`APScheduler`) that automatically runs 6-hourly NAV refreshes, daily valuation rollups, and ISIN database update checks:

```bash
# Run normal schedule
folioman scheduler run

# Run an immediate catch-up pass on startup before entering schedule
folioman scheduler run --catchup
```
