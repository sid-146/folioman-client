# Contributing to `folioman-client`

Thank you for contributing to `folioman-client`! This guide provides everything you need to know to set up your local development environment, understand our design principles, navigate the codebase, write tests, and submit high-quality pull requests.

For an exhaustive, machine-verified inventory of all 88 Python modules, 165 classes, and 525 callable functions across the repository, see the **[Codebase & Documentation Coverage Inventory](_internal/documentation_audit.md)**.

---

## 1. Development Environment Setup

We recommend using **uv** for ultra-fast environment setup and dependency synchronization. Standard `pip` and Python virtual environments (`venv`) are also supported.

- **Python Version**: `>= 3.11` (Tested against Python 3.11, 3.12, 3.13, and 3.14).

### Option A: Using `uv` (Recommended)

```bash
# Clone the repository
git clone https://github.com/sid-146/folioman-client.git
cd folioman-client

# Synchronize all dependencies including dev and optional extras
uv sync --all-extras
```

### Option B: Using standard `venv` and `pip`

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install package in editable mode with development tools
pip install -e ".[dev,postgres]"
```

---

## 2. Critical Engineering Invariants (Must Follow)

When modifying or adding code in this repository, strictly adhere to these 6 golden rules:

### Rule 1: Strict Decimal Financial Discipline
- **NEVER use IEEE 754 `float`** for currency, monetary amounts, share/unit counts, NAVs, prices, or taxes.
- **ALWAYS use `decimal.Decimal`**.
- Use `coerce_decimal` from `folioman_client.core.models.decimal_fields` for Pydantic models. It explicitly rejects `bool` and `float` inputs.
- Format numbers using string formatting (e.g., `f"{val:.4f}"`), never `float(val)`.

### Rule 2: PAN & PII Security Invariants
- Permanent Account Numbers (PANs) are sensitive financial identifiers.
- **NEVER log plaintext PANs or statement passwords.**
- **NEVER store plaintext PANs in database columns.**
- Always use helpers from `folioman_client.security.pan`:
  ```python
  from folioman_client.security.pan import normalize_pan, mask_pan, encrypt_pan, hash_pan

  pan_clean = normalize_pan(raw_pan)
  masked = mask_pan(pan_clean)         # e.g., "XXXXXX234F"
  enc_bytes = encrypt_pan(pan_clean)   # Store in pan_encrypted
  lookup_hash = hash_pan(pan_clean)    # Store in pan_hash
  ```

### Rule 3: Transaction Immutability & Corporate Actions
- Rows in the `Transaction` table (`db/models.py`) represent historical real-world financial events and are **immutable**.
- When a company undergoes a stock split, bonus issue, or merger, **do NOT mutate historical buy transaction units or prices**.
- Store actions in `CorporateActionReference` and replay them dynamically via `ProjectedLedger`.

### Rule 4: Exception Hierarchy
- Do NOT raise bare `ValueError` or generic `Exception` in public service methods or client resources.
- Extend domain exceptions in `folioman_client.errors`:
  - `FoliomanNotFoundError` (Missing investor, folio, or security)
  - `FoliomanValidationError` (Invalid parameters or parsing failures)
  - `FoliomanConflictError` (Duplicate records / state conflicts)
  - `FoliomanAuthError` (Authentication / token failures)

### Rule 5: Avoid N+1 Query Patterns
- In batch operations (such as statement imports or reconciliation), never execute individual database queries inside a loop.
- Batch lookups using SQL `IN` clauses:
  ```python
  stmt = select(Transaction.dedup_key).where(Transaction.dedup_key.in_(batch_keys))
  existing_keys = set((await session.execute(stmt)).scalars().all())
  ```

### Rule 6: No `init_schema()` in CRUD Methods
- `init_schema()` acquires exclusive table DDL locks. It must only be called during bootstrap or test setup, never inside per-request CRUD methods.

---

## 3. Step-by-Step Contribution Walkthrough

Here is an end-to-end example of adding a new feature or extending a service.

### Step 1: Create a Feature Branch
```bash
git checkout -b feature/support-crypto-pricing
```

### Step 2: Implement Domain Logic
Place pure business logic, calculations, and algorithms under `src/folioman_client/core/`. For example, create an adapter under `src/folioman_client/core/price_feeds/coingecko.py`.

### Step 3: Write Isolated Unit Tests First
Always use an in-memory SQLite database (`sqlite+aiosqlite:///:memory:`) for fast service testing:

```python
import pytest
from decimal import Decimal
from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.services.ledger_service import LedgerService

@pytest.fixture
async def ledger_service():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = LedgerService(engine=engine)
    try:
        yield service
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_my_new_feature(ledger_service: LedgerService):
    investor = await ledger_service.create_investor(
        user_id="user_123", name="Rohan Sharma", pan="ABCDE1234F"
    )
    assert investor["name"] == "Rohan Sharma"
    assert investor["pan_masked"] == "XXXXXX1234F"
```

### Step 4: Run the Test Suite
```bash
# Run entire test suite
pytest

# Run fast (fail on first error)
pytest -x

# Run your new test file specifically
pytest tests/test_my_feature.py
```

### Step 5: Format & Validate Code Quality
```bash
# Auto-format with black
black src tests

# Verify formatting without changes
black --check src tests

# Validate documentation build in strict mode
python -m mkdocs build --strict
```

---

## 4. Pull Request Checklist

Before submitting a pull request, ensure every item is checked:

- [ ] All prices, NAVs, amounts, and units use `Decimal` (no `float`).
- [ ] PANs are masked in logs and encrypted/hashed at rest.
- [ ] No `init_schema()` calls inside per-request CRUD methods.
- [ ] All database queries are batched where appropriate (no N+1 loops).
- [ ] New service methods raise `FoliomanError` subclasses, not bare `ValueError`.
- [ ] Unit tests pass: `pytest` exits with code 0.
- [ ] Code formatting passes: `black --check src tests`.
- [ ] Documentation builds cleanly: `python -m mkdocs build --strict`.
- [ ] No secrets or `.env` files committed.
