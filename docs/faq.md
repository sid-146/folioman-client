# Frequently Asked Questions (FAQ)

Answers to common architectural, usage, and financial accounting questions about `folioman-client`.

---

## Architecture & Database

### What does "embedded engine" mean in `v0.2.0+`?
Starting in `v0.2.0`, `folioman-client` is a zero-configuration, self-contained Python library with a built-in database persistence layer (backed by SQLite via `aiosqlite` by default). You do not need to host or run an external Folioman backend server. All statement ingestion, price synchronization, FIFO lot allocation, and capital gains math run directly in your Python process.

### Can I use PostgreSQL instead of SQLite?
Yes. Folioman supports PostgreSQL out-of-the-box via `psycopg3`. Install the optional dependency group:
```bash
pip install "folioman-client[postgres]"
```
And configure the connection URL via environment variable:
```bash
export FOLIOMAN_DATABASE_URL="postgresql+psycopg://user:password@localhost:5432/folioman_db"
```
Or in Python:
```python
client = FoliomanClient(
    database_url="postgresql+psycopg://user:pass@localhost:5432/folioman_db"
)
```

### Can I run `folioman-client` inside a FastAPI, Django, or Litestar web app?
Yes. Folioman is fully asynchronous (`async`/`await`) and built on SQLAlchemy 2.0 asyncio with connection pooling. Simply initialize a singleton `FoliomanClient()` at application startup and inject it into your route handlers or dependency containers.

---

## Financial Accounting & Mathematics

### Why does Folioman forbid Python `float`?
Floating-point arithmetic under IEEE 754 introduces precision errors (such as `0.1 + 0.2 = 0.30000000000000004`). In portfolio accounting, fractional rounding differences lead to balance reconciliation mismatches and invalid tax calculations. Folioman enforces `decimal.Decimal` across all models and explicitly rejects `float` and `bool` inputs via `coerce_decimal`.

### Why does Folioman not mutate historical transactions when a stock splits?
Real-world financial events are immutable. If you bought 100 shares of Reliance in 2017 at ₹1,500, modifying that transaction to 200 shares at ₹750 destroys the historical audit trail and invalidates bank reconciliation.

Instead, Folioman stores corporate action events (splits, bonus issues) in the `CorporateActionReference` table and computes adjusted units and prices on-the-fly via `ProjectedLedger`.

### How does Section 112A grandfathering handle a stock whose price dropped below its 31-Jan-2018 FMV?
Under Section 112A(4), the deemed cost formula is:
$$\text{Deemed Cost} = \max(\text{Actual Purchase Cost}, \min(\text{FMV as of 31-Jan-2018}, \text{Sale Price}))$$

If a stock was bought at ₹100, had an FMV of ₹250 on Jan 31, 2018, and was sold at ₹200:
- Deemed Cost = $\max(100, \min(250, 200)) = \max(100, 200) = ₹200$.
- Taxable Gain = ₹200 - ₹200 = ₹0.00.
The law protects the accrued pre-2018 gain from tax, but does not allow you to claim an artificial capital loss against other income.

---

## Security & PII Protection

### Where are PAN numbers stored, and are they safe?
Plaintext PANs are **never stored** in database columns and are **never logged**. Folioman uses a dual-storage scheme:
1. `pan_encrypted`: The PAN is encrypted using Fernet (AES-128 in CBC mode with HMAC-SHA256 authentication).
2. `pan_hash`: A keyed HMAC-SHA256 digest is generated to allow fast, deterministic database indexing and investor lookups without decrypting every row.

### Where does Folioman find the master encryption key?
Folioman resolves keys in this order:
1. `FOLIOMAN_PAN_SECRET` or `FOLIOMAN_ENCRYPTION_KEY` environment variable.
2. OS Credential Manager (Windows Credential Locker, macOS Keychain, Linux Secret Service).
3. Secure key file on disk (`~/.folioman/keys/master.key`, permissions `0600`).
4. If none exists, Folioman generates a cryptographically secure key and saves it to your OS credential manager.

---

## Statements & Price Feeds

### What happens if I import the same CAS PDF twice?
Folioman computes a deterministic SHA-256 hash for every transaction line (`dedup_key`). When you re-import a statement, previously imported transactions are recognized and skipped idempotently.

### What is a "Partial Block" or "Gap Detected"?
If you import a recent CAS statement that only covers the last 12 months, but your mutual fund folio was opened 5 years ago, Folioman detects that the statement's opening unit balance does not match your transaction history.

Folioman creates a `PartialBlock` to anchor the observed balance and snapshot your portfolio value accurately, while marking those specific units as `cost_basis_complete = False` until you import older historical statements.

### How often are mutual fund NAVs updated?
AMFI updates scheme NAVs on business days between 9:00 PM and 11:30 PM IST. You can configure Folioman's built-in scheduler (`folioman scheduler start`) or run `folioman nav refresh` via a nightly cron job.
