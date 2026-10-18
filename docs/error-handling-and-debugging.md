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

## 2. Centralized Database Diagnostics (`db/reporting.py`)

SQLAlchemy and driver exceptions can be deeply nested and opaque. `folioman-client` intercepts database errors and generates clean, actionable diagnostic blocks:

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

### 2.1 Diagnostic Fields
Every diagnostic block provides 8 standardized fields:
1. **Header**: The exact SQLAlchemy exception class (`[DATABASE ERROR] <class>`).
2. **Backend**: Detected database dialect (`SQLite`, `PostgreSQL`, or `Unknown`).
3. **Operation**: Database operation (`INSERT`, `SELECT`, `UPDATE`, `DELETE`, `COMMIT`, `CONNECT`).
4. **Query**: The failed SQL statement (with sensitive values redacted).
5. **Location**: True application source file and line number (e.g., `src/folioman_client/services/ledger_service.py:126`).
6. **Cause**: Concise explanation of the root cause.
7. **Fix**: Practical, actionable remediation advice.
8. **Original error**: Raw message from the underlying database driver.

### 2.2 Call-Site Resolution Architecture
In async Python, exceptions are caught deep within framework greenlets or connection pool workers. Traditional `traceback.format_exc()` often points to `aiosqlite/core.py` or `sqlalchemy/dialects/sqlite/aiosqlite.py`.

The `extract_application_location()` utility:
1. Traverses the active execution stack frames.
2. Inspects greenlet parent coroutines.
3. Automatically ignores internal framework frames (`site-packages`, `sqlalchemy`, `psycopg`, `aiosqlite`, and `folioman_client/db/`).
4. Pinpoints the exact application line in `services/`, `cli/`, or external user code that triggered the query.

### 2.3 Automatic Privacy & Secret Redaction
To protect user confidentiality in terminal output and logs:
- **Database URLs**: Passwords and connection credentials are automatically stripped:
  `postgresql+psycopg://folioman:***@localhost:5432/folioman`
- **Permanent Account Numbers**: Any 10-character PAN pattern is masked:
  `ABCDE1234F` $\to$ `XXXXXX1234`
- **Passwords & Secrets**: PDF opening passwords and API keys are redacted to `[REDACTED]`.
- **SQL Parameters**: Bound parameters are excluded from logs by default.

### 2.4 Error De-Duplication
When an error bubbles up through multiple abstraction layers (`AsyncSession` $\to$ `handle_db_errors` $\to$ `LedgerService` $\to$ CLI command), Folioman tags the exception instance with `_folioman_db_error_reported = True`. This ensures the diagnostic block is printed to `sys.stderr` **exactly once**.

---

## 3. Common Error Catalog & Corrective Actions

### 3.1 SQLite Database Locked (`OperationalError`)
- **Cause**: Another process or background thread is holding an exclusive write lock on the SQLite file.
- **Fix**: Enable WAL mode via `folioman-client` default pragmas, or ensure only one process writes to the SQLite file at a time. Consider migrating to PostgreSQL for high-concurrency environments.

### 3.2 Psycopg `ProactorEventLoop` Incompatibility
- **Cause**: On Windows, Python's default `ProactorEventLoop` is incompatible with `psycopg3` async mode.
- **Fix**: Add the following before starting the event loop:
  ```python
  import asyncio, sys
  if sys.platform == "win32":
      asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  ```

### 3.3 Unique Constraint Violation (`IntegrityError`)
- **Cause**: Attempting to insert a duplicate record (e.g. an investor with an already registered PAN hash, or a duplicate transaction).
- **Fix**: Use `CASImportService` deduplication keys or check existing records using `LedgerService.list_investors()`.

### 3.4 Connection Pool Timeout (`TimeoutError`)
- **Cause**: All database connections in the pool are exhausted by long-running queries or unclosed sessions.
- **Fix**: Ensure all sessions are managed within `async with session_factory() as session:` blocks and increase `pool_size` in settings.
