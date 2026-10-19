"""Comprehensive tests for centralized database error handling and reporting.

Covers all required failure scenarios:
1. SQLite locked database.
2. SQLite missing table.
3. SQLite integrity violation.
4. PostgreSQL connection failure.
5. PostgreSQL integrity violation.
6. PostgreSQL missing relation or column.
7. Psycopg ProactorEventLoop incompatibility.
8. Connection pool timeout.
9. Invalid SQL syntax.
10. Unknown SQLAlchemy exceptions.
Plus sensitive data redaction, de-duplication, source location accuracy, and exception chaining.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import (
    IntegrityError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)
from sqlalchemy.exc import (
    TimeoutError as SATimeoutError,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from folioman_client.db.engine import (
    create_folioman_engine,
    create_sessionmaker,
)
from folioman_client.db.errors import (
    handle_db_errors,
)
from folioman_client.db.reporting import (
    analyze_db_error,
    format_database_error,
    report_database_error,
    sanitize_message,
    sanitize_url,
)
from folioman_client.errors import (
    DuplicateInvestorError,
    FoliomanDatabaseError,
)

load_dotenv()
# Read PostgreSQL URL from .env if present
_PG_URL = os.getenv("DB_URL")


@pytest.fixture(autouse=True)
def enable_db_error_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable console reporting of database diagnostics for reporting tests."""
    monkeypatch.setenv("FOLIOMAN_DEBUG_DB_ERRORS", "1")


# -----------------------------------------------------------------------------
# 1. SQLite locked database
# -----------------------------------------------------------------------------


def test_sqlite_locked_database_diagnostics() -> None:
    """Verify SQLite locked database error diagnosis and actionable fix."""
    dbapi_err = sqlite3.OperationalError("database is locked")
    dbapi_err.sqlite_errorcode = 5  # SQLITE_BUSY
    exc = OperationalError("INSERT INTO accounts (val) VALUES (?)", {}, dbapi_err)

    info = analyze_db_error(exc, backend="SQLite")
    assert info.exception_type == "sqlalchemy.exc.OperationalError"
    assert info.backend == "SQLite"
    assert info.operation == "INSERT"
    assert "accounts" in (info.query or "")
    assert "locked by another concurrent process" in info.cause
    assert "busy_timeout" in info.fix or "WAL mode" in info.fix
    assert "database is locked" in info.original_error


@pytest.mark.asyncio
async def test_sqlite_locked_database_integration() -> None:
    """Integration test for SQLite locked database via concurrent exclusive transaction."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        raw_conn = sqlite3.connect(path, timeout=0.1)
        raw_conn.execute("CREATE TABLE t (id INT)")
        raw_conn.commit()

        # Acquire exclusive lock
        raw_conn.execute("BEGIN EXCLUSIVE")
        raw_conn.execute("INSERT INTO t VALUES (1)")

        eng = create_folioman_engine(f"sqlite+aiosqlite:///{path}")
        captured_exc: OperationalError | None = None
        try:
            async with eng.connect() as conn:
                await conn.execute(text("INSERT INTO t VALUES (2)"))
        except OperationalError as exc:
            captured_exc = exc
        finally:
            await eng.dispose()
            raw_conn.close()

        assert captured_exc is not None
        info = getattr(captured_exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "SQLite"
        assert "locked" in info.cause.lower()
        assert "database is locked" in info.original_error
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


# -----------------------------------------------------------------------------
# 2. SQLite missing table
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_missing_table(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify SQLite missing table diagnosis and fix recommendations."""
    eng = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT * FROM non_existent_table_xyz"))
    except OperationalError as exc:
        info = getattr(exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.exception_type == "sqlalchemy.exc.OperationalError"
        assert info.backend == "SQLite"
        assert info.operation == "SELECT"
        assert "SELECT * FROM non_existent_table_xyz" in (info.query or "")
        assert "test_database_error_reporting.py" in info.location
        assert "Table or relation does not exist" in info.cause
        assert "init_schema" in info.fix or "migrations" in info.fix
        assert "no such table: non_existent_table_xyz" in info.original_error
    finally:
        await eng.dispose()

    # Verify formatted stderr output
    stderr = capsys.readouterr().err
    assert "[DATABASE ERROR] sqlalchemy.exc.OperationalError" in stderr
    assert "Backend   : SQLite" in stderr
    assert "Operation : SELECT" in stderr
    assert "no such table: non_existent_table_xyz" in stderr


# -----------------------------------------------------------------------------
# 3. SQLite integrity violation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sqlite_integrity_violation() -> None:
    """Verify SQLite unique constraint violation diagnosis."""
    eng = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with eng.begin() as conn:
            await conn.execute(
                text("CREATE TABLE users (id INT PRIMARY KEY, email TEXT UNIQUE)")
            )
            await conn.execute(
                text("INSERT INTO users VALUES (1, 'alice@example.com')")
            )
            await conn.execute(
                text("INSERT INTO users VALUES (2, 'alice@example.com')")
            )
    except IntegrityError as exc:
        info = getattr(exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.exception_type == "sqlalchemy.exc.IntegrityError"
        assert info.backend == "SQLite"
        assert info.operation == "INSERT"
        assert "unique constraint was violated" in info.cause.lower()
        assert "not duplicated" in info.fix.lower()
        assert "UNIQUE constraint failed" in info.original_error
    finally:
        await eng.dispose()


# -----------------------------------------------------------------------------
# 4. PostgreSQL connection failure
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgresql_connection_failure() -> None:
    """Verify diagnosis and credential redaction when PostgreSQL server is unreachable."""
    bad_url = "postgresql+psycopg://testuser:supersecretpass@127.0.0.1:59999/testdb"
    eng = create_folioman_engine(bad_url)
    try:
        async with eng.connect():
            pass
    except (OperationalError, InterfaceError) as exc:
        # On Windows, psycopg might fail with Proactor or connection refused depending on loop
        info = getattr(exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "PostgreSQL"
        assert info.operation == "Database connection"
        assert info.query is None or info.query == "Not available"
        # Verify secrets are NOT exposed
        formatted = format_database_error(info)
        assert "supersecretpass" not in formatted
        assert "supersecretpass" not in info.original_error
    finally:
        await eng.dispose()


# -----------------------------------------------------------------------------
# 5. PostgreSQL integrity violation
# -----------------------------------------------------------------------------


def test_postgresql_integrity_violation_unit() -> None:
    """Unit test for PostgreSQL unique constraint violation using mocked DBAPI error."""
    mock_orig = MagicMock()
    mock_orig.sqlstate = "23505"
    mock_orig.__str__ = lambda self: (
        'duplicate key value violates unique constraint "users_email_key"'
    )

    exc = IntegrityError(
        "INSERT INTO users (email) VALUES (%s)",
        {"email": "dup@example.com"},
        mock_orig,
    )
    info = analyze_db_error(exc, backend="PostgreSQL")
    assert info.exception_type == "sqlalchemy.exc.IntegrityError"
    assert info.backend == "PostgreSQL"
    assert info.operation == "INSERT"
    assert "unique constraint was violated" in info.cause.lower()
    assert "not duplicated" in info.fix.lower()
    assert "users_email_key" in info.original_error


@pytest.mark.skipif(not _PG_URL, reason="PostgreSQL endpoint not configured in .env")
def test_postgresql_integrity_violation_live() -> None:
    """Live integration test against PostgreSQL endpoint from .env."""

    async def run_test() -> None:
        eng = create_folioman_engine(_PG_URL)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text("CREATE TEMPORARY TABLE test_uniq_live (id INT PRIMARY KEY)")
                )
                await conn.execute(text("INSERT INTO test_uniq_live VALUES (1)"))
                await conn.execute(text("INSERT INTO test_uniq_live VALUES (1)"))
        finally:
            await eng.dispose()

    # Use SelectorEventLoop if on Windows to allow psycopg async connection
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        with pytest.raises(IntegrityError) as exc_info:
            runner.run(run_test())

        info = getattr(exc_info.value, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "PostgreSQL"
        assert info.operation == "INSERT"
        assert "unique constraint was violated" in info.cause.lower()
        assert "duplicate key value violates unique constraint" in info.original_error


# -----------------------------------------------------------------------------
# 6. PostgreSQL missing relation or column
# -----------------------------------------------------------------------------


def test_postgresql_missing_relation_unit() -> None:
    """Unit test for PostgreSQL undefined table (42P01)."""
    mock_orig = MagicMock()
    mock_orig.sqlstate = "42P01"
    mock_orig.__str__ = lambda self: 'relation "unknown_table" does not exist'

    exc = ProgrammingError("SELECT * FROM unknown_table", {}, mock_orig)
    info = analyze_db_error(exc, backend="PostgreSQL")
    assert info.exception_type == "sqlalchemy.exc.ProgrammingError"
    assert info.backend == "PostgreSQL"
    assert info.operation == "SELECT"
    assert "Table or relation does not exist" in info.cause
    assert "init_schema" in info.fix or "migrations" in info.fix
    assert 'relation "unknown_table" does not exist' in info.original_error


def test_postgresql_missing_column_unit() -> None:
    """Unit test for PostgreSQL undefined column (42703)."""
    mock_orig = MagicMock()
    mock_orig.sqlstate = "42703"
    mock_orig.__str__ = lambda self: 'column "non_existent_col" does not exist'

    exc = ProgrammingError("SELECT non_existent_col FROM users", {}, mock_orig)
    info = analyze_db_error(exc, backend="PostgreSQL")
    assert info.exception_type == "sqlalchemy.exc.ProgrammingError"
    assert info.backend == "PostgreSQL"
    assert info.operation == "SELECT"
    assert "Referenced column does not exist" in info.cause
    assert "column names" in info.fix.lower()
    assert 'column "non_existent_col" does not exist' in info.original_error


@pytest.mark.skipif(not _PG_URL, reason="PostgreSQL endpoint not configured in .env")
def test_postgresql_missing_relation_live() -> None:
    """Live integration test for PostgreSQL missing table."""

    async def run_test() -> None:
        eng = create_folioman_engine(_PG_URL)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("SELECT * FROM non_existent_pg_rel_xyz"))
        finally:
            await eng.dispose()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        with pytest.raises(ProgrammingError) as exc_info:
            runner.run(run_test())

        info = getattr(exc_info.value, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "PostgreSQL"
        assert info.operation == "SELECT"
        assert "Table or relation does not exist" in info.cause
        assert (
            'relation "non_existent_pg_rel_xyz" does not exist' in info.original_error
        )


# -----------------------------------------------------------------------------
# 7. Psycopg ProactorEventLoop incompatibility
# -----------------------------------------------------------------------------


def test_psycopg_proactor_event_loop_unit() -> None:
    """Verify diagnosis of Psycopg ProactorEventLoop incompatibility."""
    msg = (
        "Psycopg cannot use the 'ProactorEventLoop' to run in async mode. "
        "Please use a compatible event loop, for instance by running "
        "'asyncio.run(..., loop_factory=asyncio.SelectorEventLoop(selectors.SelectSelector()))'"
    )
    orig_err = InterfaceError(None, None, Exception(msg))
    info = analyze_db_error(orig_err, backend="PostgreSQL")

    assert info.exception_type == "sqlalchemy.exc.InterfaceError"
    assert info.backend == "PostgreSQL"
    assert info.operation == "Database connection"
    assert info.query is None
    assert (
        "The psycopg async driver is incompatible with the active event loop."
        in info.cause
    )
    assert (
        "Verify async driver configuration and use a compatible event loop" in info.fix
    )
    assert (
        "or use a synchronous engine and driver if async access is unnecessary."
        in info.fix
    )
    assert (
        info.original_error
        == "Psycopg cannot use the 'ProactorEventLoop' to run in async mode."
    )

    # Verify formatting adheres to specification
    formatted = format_database_error(info)
    assert "[DATABASE ERROR] sqlalchemy.exc.InterfaceError" in formatted
    assert "Backend   : PostgreSQL" in formatted
    assert "Operation : Database connection" in formatted
    assert "Query     : Not available" in formatted
    assert (
        "Cause     : The psycopg async driver is incompatible with the active event loop."
        in formatted
    )


@pytest.mark.skipif(
    sys.platform != "win32" or not _PG_URL, reason="Windows & PostgreSQL required"
)
@pytest.mark.asyncio
async def test_psycopg_proactor_event_loop_live_windows() -> None:
    """Live verification of Psycopg ProactorEventLoop error under default Windows event loop."""
    eng = create_folioman_engine(_PG_URL)
    try:
        async with eng.connect():
            pass
    except InterfaceError as exc:
        info = getattr(exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "PostgreSQL"
        assert info.operation == "Database connection"
        assert (
            "The psycopg async driver is incompatible with the active event loop."
            in info.cause
        )
        assert (
            "Psycopg cannot use the 'ProactorEventLoop' to run in async mode."
            in info.original_error
        )
    finally:
        await eng.dispose()


# -----------------------------------------------------------------------------
# 8. Connection pool timeout
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_pool_timeout() -> None:
    """Verify connection pool exhaustion timeout handling."""
    eng = create_folioman_engine(
        "sqlite+aiosqlite:///:memory:",
    )
    # Reconfigure pool for timeout testing
    pool_eng = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    # Create an engine with limited pool
    from sqlalchemy.ext.asyncio import create_async_engine

    from folioman_client.db.engine import FoliomanAsyncEngine

    base = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    test_eng = FoliomanAsyncEngine(base.sync_engine)

    conn1 = await test_eng.connect()
    try:
        with pytest.raises(SATimeoutError) as exc_info:
            await test_eng.connect()

        info = getattr(exc_info.value, "_folioman_db_error_info", None)
        assert info is not None
        assert info.exception_type == "sqlalchemy.exc.TimeoutError"
        assert (
            info.operation == "Database connection"
            or info.operation == "Connection acquisition"
        )
        assert "Connection pool exhausted" in info.cause
        assert "pool_size" in info.fix or "pool_timeout" in info.fix
        assert "QueuePool limit of size 1 overflow 0 reached" in info.original_error
    finally:
        await conn1.close()
        await test_eng.dispose()
        await eng.dispose()
        await pool_eng.dispose()


# -----------------------------------------------------------------------------
# 9. Invalid SQL syntax
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_sql_syntax() -> None:
    """Verify invalid SQL statement syntax error handling."""
    eng = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECCT 123"))
    except OperationalError as exc:
        info = getattr(exc, "_folioman_db_error_info", None)
        assert info is not None
        assert info.backend == "SQLite"
        assert "SELECCT 123" in (info.query or "")
        assert "syntax errors or invalid statements" in info.cause.lower()
        assert "syntax" in info.fix.lower()
        assert "syntax error" in info.original_error.lower()
    finally:
        await eng.dispose()


# -----------------------------------------------------------------------------
# 10. Unknown SQLAlchemy exceptions
# -----------------------------------------------------------------------------


def test_unknown_sqlalchemy_exception() -> None:
    """Verify unknown SQLAlchemy errors preserve original message without guessing."""
    exc = SQLAlchemyError(
        "Custom driver crashed with unexpected internal error code 99"
    )
    info = analyze_db_error(exc)

    assert info.exception_type == "sqlalchemy.exc.SQLAlchemyError"
    assert info.backend == "Unknown"
    assert info.operation == "Unknown"
    assert info.query is None
    assert "Database operation failed: Custom driver crashed" in info.cause
    assert "Inspect the original error details" in info.fix
    assert (
        "Custom driver crashed with unexpected internal error code 99"
        in info.original_error
    )


# -----------------------------------------------------------------------------
# 11. Sensitive Data Redaction
# -----------------------------------------------------------------------------


def test_sensitive_data_redaction() -> None:
    """Verify that credentials, tokens, and PANs are strictly redacted."""
    # Database URL password
    url = "postgresql+psycopg://myuser:SuperSecretPassword123@db.example.com:5432/folio"
    clean_url = sanitize_url(url)
    assert "SuperSecretPassword123" not in clean_url
    assert clean_url == "postgresql+psycopg://myuser:***@db.example.com:5432/folio"

    # SQL with password
    sql = "ALTER USER investor WITH PASSWORD 'MySecretP@ssword!';"
    info = analyze_db_error(OperationalError(sql, {}, Exception("auth err")))
    assert "MySecretP@ssword!" not in (info.query or "")

    # Message with PAN
    msg = "Failed query for investor with pan ABCDE1234F"
    clean_msg = sanitize_message(msg)
    assert "ABCDE1234F" not in clean_msg
    assert "XXXXXX234F" in clean_msg


# -----------------------------------------------------------------------------
# 12. De-duplication (no double printing)
# -----------------------------------------------------------------------------


def test_error_deduplication(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that an error is printed to console only once even when handled at multiple layers."""
    exc = OperationalError(
        "SELECT * FROM tbl", {}, sqlite3.OperationalError("no such table: tbl")
    )

    # First report call -> writes to stderr
    info1 = report_database_error(exc, backend="SQLite")
    captured = capsys.readouterr()
    assert "[DATABASE ERROR]" in captured.err

    # Second report call on same exception -> should NOT write again
    info2 = report_database_error(exc, backend="SQLite")
    captured2 = capsys.readouterr()
    assert captured2.err == ""
    assert info1 == info2


@pytest.mark.asyncio
async def test_session_and_handle_db_errors_deduplication(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify that error bubbling from FoliomanAsyncSession through handle_db_errors prints once."""
    eng = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_sessionmaker(eng)

    try:
        async with session_factory() as session, handle_db_errors(session):
            await session.execute(text("SELECT * FROM table_does_not_exist"))
    except FoliomanDatabaseError:
        pass
    finally:
        await eng.dispose()

    captured = capsys.readouterr()
    # Count occurrences of [DATABASE ERROR] header
    count = captured.err.count("[DATABASE ERROR]")
    assert count == 1, f"Expected exactly 1 error header, got {count}"


# -----------------------------------------------------------------------------
# 13. Exception Chaining & Traceback Preservation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exception_chaining_preserved() -> None:
    """Verify that handle_db_errors preserves __cause__ and original exception traceback."""
    session_mock = MagicMock()
    session_mock.rollback = MagicMock()

    orig_exc = IntegrityError(
        "INSERT ...",
        {},
        sqlite3.IntegrityError("UNIQUE constraint failed: investors.pan_hash"),
    )

    with pytest.raises(DuplicateInvestorError) as exc_info:
        async with handle_db_errors(session_mock):
            raise orig_exc

    err = exc_info.value
    # __cause__ must be the original IntegrityError
    assert err.__cause__ is orig_exc
    assert err.__cause__.__traceback__ is not None


@pytest.mark.asyncio
async def test_statement_error_location_and_chaining() -> None:
    """Verify that StatementError includes file/line location and preserves exception chaining."""
    from sqlalchemy.exc import StatementError

    session_mock = MagicMock()
    session_mock.rollback = MagicMock()

    orig_exc = StatementError(
        "cannot adapt type DeclarativeAttributeIntercept",
        "SELECT CAST(:param_1 AS TEXT)",
        {"param_1": "dummy"},
        None,
    )

    with pytest.raises(FoliomanDatabaseError) as exc_info:
        async with handle_db_errors(session_mock):
            raise orig_exc

    err = exc_info.value
    assert err.__cause__ is orig_exc
    assert err.__cause__.__traceback__ is not None
    # Must include line number and location
    assert "test_database_error_reporting.py" in str(err)
    assert "StatementError" in str(err)
    assert "cannot adapt type DeclarativeAttributeIntercept" in str(err)
    assert err.location is not None
    assert "test_database_error_reporting.py" in err.location
    assert err.orig_error == "cannot adapt type DeclarativeAttributeIntercept"
