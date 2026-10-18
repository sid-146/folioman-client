# Error Handling & Debugging Guide

This document explains the exception hierarchy, centralized database error reporting mechanism, secret redaction, and troubleshooting strategies in `folioman-client`.

---

## 1. Exception Hierarchy (`folioman_client.errors`)

All domain exceptions inherit from the base `FoliomanError`:

```mermaid
classDiagram
    class Exception
    class FoliomanError {
        +status_code: int
        +details: dict
    }
    class FoliomanAuthError {
        +status_code = 401
    }
    class FoliomanNotFoundError {
        +status_code = 404
    }
    class FoliomanValidationError {
        +status_code = 422
    }
    class FoliomanPasswordError {
        +status_code = 400
    }
    class FoliomanParseError {
        +status_code = 400
    }
    class FoliomanConflictError {
        +status_code = 409
    }
    class FoliomanDatabaseError {
        +status_code = 500
    }

    Exception <|-- FoliomanError
    FoliomanError <|-- FoliomanAuthError
    FoliomanError <|-- FoliomanNotFoundError
    FoliomanError <|-- FoliomanValidationError
    FoliomanValidationError <|-- FoliomanPasswordError
    FoliomanValidationError <|-- FoliomanParseError
    FoliomanError <|-- FoliomanConflictError
    FoliomanError <|-- FoliomanDatabaseError
```

### Exception Usage Guidelines:
- `FoliomanNotFoundError`: Raised when an investor, folio, security, or job ID does not exist in the database.
- `FoliomanPasswordError`: Raised when a user-supplied password fails to decrypt a CAS or eCAS PDF statement.
- `FoliomanParseError`: Raised when a statement PDF is malformed, truncated, or unparseable.
- `FoliomanConflictError`: Raised on duplicate record conflicts (e.g. folio already exists).
- `FoliomanDatabaseError`: Raised when an unrecoverable database driver failure occurs.

---

## 2. Actionable Domain Messages (SDK & CLI Parity)

`folioman-client` enforces consistent, clean, and actionable error messages whether using the Python SDK or the `folioman` command-line interface.

### 2.1 Exception Translation inside `handle_db_errors`
Database queries within services are guarded by the `handle_db_errors(session)` context manager (`folioman_client.db.errors`):

- **Missing Tables / Schema**: Automatically translates SQLite and PostgreSQL `OperationalError` into a clear `FoliomanDatabaseError`:
  ```text
  Table or relation does not exist in the database schema. Verify the table name and run database schema migrations (init_schema) to create missing tables.
  ```
- **Driver Traceback Suppression**: Translated exceptions are raised with `from None` (`raise translate_operational_error(exc) from None`), stripping internal SQLAlchemy greenlet and DBAPI driver tracebacks from user-facing exceptions.
- **Unique Constraints**: Specific constraints like `uniq_investor_user_pan` are mapped directly to `DuplicateInvestorError("An investor with this PAN already exists for this user.")`.

### 2.2 Terminal Output Parity
When executed via the CLI, commands intercept `(FoliomanError, ValueError)` and raise `click.ClickException(str(exc))`. Furthermore, the root `FoliomanCLI` Click group catches any unhandled domain exceptions.

This guarantees that:
- The exact same actionable message is provided across SDK and CLI:
  ```console
  $ folioman portfolio summary --investor-id 1
  Error: Table or relation does not exist in the database schema. Verify the table name and run database schema migrations (init_schema) to create missing tables.
  ```
- Raw SQL query dumps, multi-line column listings, and unhandled Python tracebacks are completely suppressed during normal usage.

---

## 3. Centralized Database Diagnostics (`db/reporting.py`)

SQLAlchemy and driver exceptions can be deeply nested and opaque. `folioman-client` includes an internal diagnostic engine that inspects call stacks and provides structured metadata.

```text
[DATABASE ERROR] sqlalchemy.exc.IntegrityError

Backend   : SQLite
Operation : INSERT
Query     : INSERT INTO investors (user_id, name, pan_hash) VALUES (?, ?, ?)
Location  : src/folioman_client/services/ledger_service.py:126
Cause     : Unique constraint failed: investors.pan_hash
Fix       : An investor with this PAN or unique identifier already exists.

Original error:
UNIQUE constraint failed: investors.pan_hash
```

### 3.1 Diagnostic Fields
Every diagnostic block provides 8 standardized fields:
1. **Header**: The exact SQLAlchemy exception class (`[DATABASE ERROR] <class>`).
2. **Backend**: Detected database dialect (`SQLite`, `PostgreSQL`, or `Unknown`).
3. **Operation**: Database operation (`INSERT`, `SELECT`, `UPDATE`, `DELETE`, `COMMIT`, `CONNECT`).
4. **Query**: The failed SQL statement (with sensitive values redacted).
5. **Location**: True application source file and line number (e.g., `src/folioman_client/services/ledger_service.py:126`).
6. **Cause**: Concise explanation of the root cause.
7. **Fix**: Practical, actionable remediation advice.
8. **Original error**: Raw message from the underlying database driver.

### 3.2 Call-Site Resolution Architecture
In async Python, exceptions are caught deep within framework greenlets or connection pool workers. Traditional `traceback.format_exc()` often points to `aiosqlite/core.py` or `sqlalchemy/dialects/sqlite/aiosqlite.py`.

The `extract_application_location()` utility:
1. Traverses the active execution stack frames.
2. Inspects greenlet parent coroutines.
3. Automatically ignores internal framework frames (`site-packages`, `sqlalchemy`, `psycopg`, `aiosqlite`, and `folioman_client/db/`).
4. Pinpoints the exact application line in `services/`, `cli/`, or external user code that triggered the query.

### 3.3 Diagnostic Output & Debug Mode (`FOLIOMAN_DEBUG_DB_ERRORS`)
By default, `report_database_error` attaches the structured `DatabaseErrorInfo` to the exception instance (`exc._folioman_db_error_info`) and logs the full diagnostic block at `logger.debug` level.

To enable verbose printing of the diagnostic banner to `sys.stderr` (e.g., during development or debugging integration tests), set the environment variable:

```bash
export FOLIOMAN_DEBUG_DB_ERRORS=1
```

### 3.4 Automatic Privacy & Secret Redaction
To protect user confidentiality in terminal output and logs:
- **Database URLs**: Passwords and connection credentials are automatically stripped:
  `postgresql+psycopg://folioman:***@localhost:5432/folioman`
- **Permanent Account Numbers**: Any 10-character PAN pattern is masked:
  `ABCDE1234F` $\to$ `XXXXXX1234`
- **Passwords & Secrets**: PDF opening passwords and API keys are redacted to `***`.
- **SQL Parameters**: Bound parameters are excluded from logs by default.

### 3.5 Error De-Duplication
When an error bubbles up through multiple abstraction layers (`AsyncSession` $\to$ `handle_db_errors` $\to$ `LedgerService` $\to$ CLI command), Folioman tags the exception instance with `_folioman_db_error_reported = True`. This ensures the diagnostic block is logged or reported **exactly once**.

---

## 4. Common Error Catalog & Corrective Actions

### 4.1 Missing Database Tables / Uninitialized Schema
- **Cause**: The database file or schema has not been bootstrapped with tables.
- **Fix**: Run schema migrations or initialize the database via CLI or Python:
  ```bash
  folioman isin seed
  ```
  ```python
  from folioman_client.db import init_schema
  await init_schema(engine)
  ```

### 4.2 SQLite Database Locked (`OperationalError`)
- **Cause**: Another process or background thread is holding an exclusive write lock on the SQLite file.
- **Fix**: Enable WAL mode via `folioman-client` default pragmas, or ensure only one process writes to the SQLite file at a time. Consider migrating to PostgreSQL for high-concurrency environments.

### 4.3 Psycopg `ProactorEventLoop` Incompatibility
- **Cause**: On Windows, Python's default `ProactorEventLoop` is incompatible with `psycopg3` async mode.
- **Fix**: Add the following before starting the event loop:
  ```python
  import asyncio, sys
  if sys.platform == "win32":
      asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  ```

### 4.4 Unique Constraint Violation (`IntegrityError`)
- **Cause**: Attempting to insert a duplicate record (e.g. an investor with an already registered PAN hash, or a duplicate transaction).
- **Fix**: Use `CASImportService` deduplication keys or check existing records using `LedgerService.list_investors()`.

### 4.5 Connection Pool Timeout (`TimeoutError`)
- **Cause**: All database connections in the pool are exhausted by long-running queries or unclosed sessions.
- **Fix**: Ensure all sessions are managed within `async with session_factory() as session:` blocks and increase `pool_size` in settings.
