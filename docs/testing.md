# Testing & Verification Guide

This document explains the testing architecture, fixture design, test suites, and guidelines for authoring tests in `folioman-client`.

---

## 1. Test Suite Architecture

The repository contains **32 test modules** comprising **247 automated tests** covering database operations, domain math, statement parsers, corporate actions, and error diagnostics.

### 1.1 Key Principles:
1. **Full Isolation**: Tests run against transient, in-memory SQLite databases (`sqlite+aiosqlite:///:memory:`). No state leaks between tests.
2. **Deterministic Async**: Configured with `pytest-asyncio` in `auto` mode. Every async test gets its own fresh event loop.
3. **Mocked Market Feeds**: External network feeds (AMFI, Yahoo Finance, mfapi) are mocked in unit tests to ensure fast, offline execution.

---

## 2. Running Tests

### 2.1 Complete Test Suite
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run and stop on first failure
pytest -x
```

### 2.2 Coverage Reporting
```bash
# Run with line coverage
pytest --cov=folioman_client tests/

# Generate detailed HTML coverage report
pytest --cov=folioman_client --cov-report=html tests/
```

### 2.3 Running Specific Test Suites
```bash
# Test centralized database error reporting
pytest tests/test_database_error_reporting.py

# Test FIFO lot accounting
pytest tests/test_fifo.py

# Test XIRR mathematical solver
pytest tests/test_xirr.py

# Test Schedule 112A tax engine
pytest tests/test_capital_gains_service.py
```

---

## 3. Test Fixture Recipes

### 3.1 Isolated Database Fixture Pattern
When writing service tests, always use an in-memory SQLite engine that initializes and disposes cleanly:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.services.ledger_service import LedgerService

@pytest.fixture
async def test_engine():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    try:
        yield engine
    finally:
        await engine.dispose()

@pytest.fixture
async def ledger_service(test_engine: AsyncEngine):
    return LedgerService(engine=test_engine)

@pytest.mark.asyncio
async def test_create_and_fetch_investor(ledger_service: LedgerService):
    investor = await ledger_service.create_investor(
        user_id="test_user",
        name="Ananya Sharma",
        pan="ABCDE1234F"
    )
    assert investor["name"] == "Ananya Sharma"
    assert investor["pan_masked"] == "XXXXXX234F"
    assert investor["has_pan"] is True
```

### 3.2 Testing CLI Commands with `CliRunner`
Click CLI commands can be tested without spawning shell subprocesses:

```python
from click.testing import CliRunner
from folioman_client.cli.main import cli

def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "folioman" in result.output
```

---

## 4. Test Suite Map

| Test Module | Coverage Area |
| :--- | :--- |
| `tests/test_database_error_reporting.py` | Centralized database error diagnostics, location extraction, and redaction (19 tests). |
| `tests/test_fifo.py` | FIFO lot queue, intraday netting, and cost basis preservation. |
| `tests/test_xirr.py` | Newton-Raphson solver and bisection fallback edge cases. |
| `tests/test_parser.py` | CAS line parsing, charge allocation, and reversal cancellation. |
| `tests/test_cas_reader.py` | PDF password decryption and table extraction. |
| `tests/test_corporate_actions.py` | Stock splits, reverse splits, bonus issues, and mergers. |
| `tests/test_corporate_action_detect.py` | Rational ratio solver and mismatch suggestion heuristics. |
| `tests/test_capital_gains_service.py` | Schedule 112A calculations, Budget 2024 cutoff, and grandfathering. |
| `tests/test_reconciliation_service.py` | Balance verification and discrepancy classification. |
| `tests/test_nav_service.py` | Price feed adapters, lag detection, and gap backfilling. |
| `tests/test_ledger_service.py` | Investor, folio, transaction, and opening lot CRUD. |
| `tests/test_pan_security.py` | Fernet PAN encryption, masking, and HMAC blind indexing. |
| `tests/test_cli_*.py` | Click command line interfaces and output formatting. |
