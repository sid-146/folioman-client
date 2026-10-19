"""Centralized database error diagnostic and reporting mechanism for Folioman.

Provides actionable, structured console reporting for database failures across SQLite
and PostgreSQL backends without introducing external dependencies or verbose logs.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
    StatementError,
)
from sqlalchemy.exc import (
    TimeoutError as SATimeoutError,
)

logger = logging.getLogger("folioman_client.db")

_INTERNAL_FILE_PATTERNS = (
    "site-packages",
    "dist-packages",
    "/lib/python",
    "\\lib\\python",
    "<frozen",
    "folioman_client/db/reporting.py",
    "folioman_client\\db\\reporting.py",
    "folioman_client/db/errors.py",
    "folioman_client\\db\\errors.py",
    "folioman_client/db/engine.py",
    "folioman_client\\db\\engine.py",
)

# Regex patterns for credential & PII sanitization
_RE_URL_PASSWORD = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:]+):([^@\s]+)@")
_RE_KEY_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|token|api_key|auth_token|bearer)\s*([=:])\s*([^\s,;'\"]+)"
)
_RE_SQL_PASSWORD = re.compile(
    r"(?i)\b(identified\s+by|with\s+password)\s+(['\"]?[^\s,;'\"]+['\"]?)"
)
_RE_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_RE_SQLA_BG_URL = re.compile(
    r"\s*\(Background on this error at:\s*https?://sqlalche\.me/[^\)]+\)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DatabaseErrorInfo:
    """Structured diagnostic information for a database error."""

    exception_type: str
    backend: str
    operation: str
    query: str | None
    location: str
    cause: str
    fix: str
    original_error: str


def sanitize_url(url: str) -> str:
    """Mask credentials in database connection URLs."""
    if not url:
        return ""
    return _RE_URL_PASSWORD.sub(r"\1:***@", url)


def mask_pan(pan_str: str) -> str:
    """Mask PAN to keep last 4 digits visible (e.g. XXXXXX234F)."""
    if len(pan_str) == 10:
        return "XXXXXX" + pan_str[6:]
    return "***"


def sanitize_message(text: str) -> str:
    """Redact passwords, secret tokens, connection credentials, and PANs from error strings."""
    if not text:
        return ""
    cleaned = _RE_URL_PASSWORD.sub(r"\1:***@", text)
    cleaned = _RE_KEY_SECRET.sub(r"\1\2***", cleaned)
    cleaned = _RE_SQL_PASSWORD.sub(r"\1 ***", cleaned)
    cleaned = _RE_PAN.sub(lambda m: mask_pan(m.group(0)), cleaned)
    cleaned = _RE_SQLA_BG_URL.sub("", cleaned)
    return cleaned.strip()


def sanitize_query(query: str | None) -> str | None:
    """Clean and sanitize SQL query string, omitting bind parameters and masking secrets."""
    if not query:
        return None
    cleaned = sanitize_message(query.strip())
    # Collapse multiple whitespaces/newlines for clean single-block output if reasonable
    return cleaned if cleaned else None


def _is_internal_frame(filename: str) -> bool:
    """Check if the frame filename belongs to internal libraries or framework plumbing."""
    fn_lower = filename.lower().replace("\\", "/")
    for pattern in _INTERNAL_FILE_PATTERNS:
        if pattern.replace("\\", "/").lower() in fn_lower:
            return True
    return False


def _normalize_location_path(filename: str, lineno: int) -> str:
    """Convert absolute file path to a concise repo-relative or normalized path."""
    if not filename or filename.startswith("<"):
        return f"{filename}:{lineno}"
    try:
        cwd = os.getcwd()
        rel = os.path.relpath(filename, cwd)
        if not rel.startswith(".."):
            norm = rel.replace("\\", "/")
            return f"{norm}:{lineno}"
    except (ValueError, OSError):
        pass
    norm = os.path.normpath(filename).replace("\\", "/")
    return f"{norm}:{lineno}"


def extract_application_location(
    exc: BaseException | None = None,
    tb: TracebackType | None = None,
) -> str:
    """Accurately identify the application source file and line initiating the database call.

    Walks exception tracebacks or greenlet parent frames to find the caller,
    strictly skipping internal SQLAlchemy, driver, and stdlib frames.
    """
    target_tb = tb or (getattr(exc, "__traceback__", None) if exc else None)

    # 1. Walk exception traceback backwards from leaf to root
    if target_tb is not None:
        frames: list[tuple[Any, int]] = []
        curr: TracebackType | None = target_tb
        while curr is not None:
            frames.append((curr.tb_frame, curr.tb_lineno))
            curr = curr.tb_next

        for frame, lineno in reversed(frames):
            filename = frame.f_code.co_filename
            if not _is_internal_frame(filename):
                return _normalize_location_path(filename, lineno)

    # 2. If running within greenlet runner (SQLAlchemy async engine), inspect parent coroutine frame
    try:
        import greenlet  # type: ignore[import-untyped]

        cur_g = greenlet.getcurrent()
        parent_g = getattr(cur_g, "parent", None) if cur_g else None
        if parent_g and hasattr(parent_g, "gr_frame") and parent_g.gr_frame:
            f = parent_g.gr_frame
            while f:
                filename = f.f_code.co_filename
                if not _is_internal_frame(filename):
                    return _normalize_location_path(filename, f.f_lineno)
                f = f.f_back
    except (ImportError, AttributeError, RuntimeError):
        pass

    # 3. Fallback: inspect the current execution call stack
    try:
        f = sys._getframe()
        while f:
            filename = f.f_code.co_filename
            if not _is_internal_frame(filename):
                return _normalize_location_path(filename, f.f_lineno)
            f = f.f_back
    except (AttributeError, ValueError):
        pass

    return "Unknown"


def detect_backend(
    exc: BaseException | None = None,
    dialect_name: str | None = None,
    url: str | None = None,
) -> str:
    """Determine the database backend name (SQLite, PostgreSQL, MySQL, etc.)."""
    if dialect_name:
        name = dialect_name.lower()
        if "sqlite" in name:
            return "SQLite"
        if "postgres" in name:
            return "PostgreSQL"
        if "mysql" in name:
            return "MySQL"
        if "mariadb" in name:
            return "MariaDB"
        if "oracle" in name:
            return "Oracle"
        return dialect_name.capitalize()

    if url:
        u = url.lower()
        if "sqlite" in u:
            return "SQLite"
        if "postgres" in u:
            return "PostgreSQL"
        if "mysql" in u:
            return "MySQL"

    if exc is not None:
        # Check driver error types
        orig = getattr(exc, "orig", None)
        target = orig if orig is not None else exc
        mod = getattr(target.__class__, "__module__", "").lower()
        msg = str(target).lower()

        if "sqlite" in mod or "aiosqlite" in mod or "sqlite" in msg:
            return "SQLite"
        if (
            "psycopg" in mod
            or "asyncpg" in mod
            or "postgresql" in msg
            or "psycopg" in msg
        ):
            return "PostgreSQL"
        if "mysql" in mod:
            return "MySQL"

    return "Unknown"


def detect_operation_and_query(
    exc: BaseException,
    statement: Any | None = None,
    operation_hint: str | None = None,
) -> tuple[str, str | None]:
    """Extract the operation type and SQL query without bound parameters."""
    raw_query: str | None = None

    if statement is not None:
        raw_query = str(statement).strip()
    elif isinstance(exc, StatementError) and getattr(exc, "statement", None):
        raw_query = str(exc.statement).strip()

    query = sanitize_query(raw_query) if raw_query else None

    # If query is available, determine operation from first SQL token
    if query:
        # Strip potential SQL comments
        cleaned = re.sub(r"/\*.*?\*/", "", query, flags=re.DOTALL).strip()
        first_token = cleaned.split()[0].upper() if cleaned else ""
        if first_token in {
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "PRAGMA",
            "ALTER",
            "DROP",
        }:
            if first_token == "CREATE":
                words = cleaned.split()
                if len(words) > 1 and words[1].upper() == "TABLE":
                    return "CREATE TABLE", query
                return "CREATE", query
            return first_token, query
        if first_token == "CREATE":
            words = cleaned.split()
            if len(words) > 1 and words[1].upper() == "TABLE":
                return "CREATE TABLE", query
            return "CREATE", query
        return first_token or "SQL query", query

    if operation_hint:
        return operation_hint, None

    # Infer operation from exception nature
    orig_msg = str(getattr(exc, "orig", exc)).lower()
    is_conn = (
        getattr(exc, "is_connection_error", False)
        or isinstance(exc, InterfaceError)
        or "proactoreventloop" in orig_msg
        or "connection refused" in orig_msg
        or "could not connect to server" in orig_msg
        or "authentication failed" in orig_msg
    )
    if is_conn:
        return "Database connection", None

    if (
        isinstance(exc, SATimeoutError)
        or "queuepool" in orig_msg
        or "timeout" in orig_msg
    ):
        return "Connection acquisition", None

    return "Unknown", None


def _extract_driver_code(orig: Any) -> tuple[str | None, str | None]:
    """Extract driver-specific error codes (sqlstate, pgcode, sqlite_errorcode)."""
    if orig is None:
        return None, None
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    sqlite_code = getattr(orig, "sqlite_errorcode", None)
    code_str = str(sqlstate) if sqlstate is not None else None
    sqlite_str = str(sqlite_code) if sqlite_code is not None else None
    return code_str, sqlite_str


def classify_cause_and_fix(
    exc: BaseException,
    backend: str,
    orig_msg: str,
) -> tuple[str, str]:
    """Diagnose the root cause and provide practical corrective action."""
    msg_lower = orig_msg.lower()
    orig = getattr(exc, "orig", None)
    sqlstate, sqlite_code = _extract_driver_code(orig)

    # 1. Psycopg ProactorEventLoop incompatibility on Windows
    if "proactoreventloop" in msg_lower and (
        "psycopg" in msg_lower or backend == "PostgreSQL"
    ):
        cause = "The psycopg async driver is incompatible with the active event loop."
        fix = (
            "Verify async driver configuration and use a compatible event loop,\n"
            "or use a synchronous engine and driver if async access is unnecessary."
        )
        return cause, fix

    # 2. SQLite locked database
    if backend == "SQLite" and (
        sqlite_code in ("5", "6")  # SQLITE_BUSY, SQLITE_LOCKED
        or "database is locked" in msg_lower
        or "database table is locked" in msg_lower
        or "locked" in msg_lower
    ):
        cause = "The SQLite database is locked by another concurrent process or unclosed transaction."
        fix = "Ensure transactions are short and closed promptly, enable WAL mode, or increase busy_timeout."
        return cause, fix

    # 3. Connection pool checkout timeout
    if (
        isinstance(exc, SATimeoutError)
        or "queuepool" in msg_lower
        or "pool timeout" in msg_lower
    ):
        cause = (
            "Connection pool exhausted; all available database connections are in use."
        )
        fix = "Increase pool_size/max_overflow, increase pool_timeout, or ensure connections and sessions are closed promptly."
        return cause, fix

    # 4. PostgreSQL Connection & Authentication Failures
    if sqlstate == "28P01" or "password authentication failed" in msg_lower:
        cause = "Database authentication failed for the specified user."
        fix = "Verify database username and password in connection settings or environment variables."
        return cause, fix

    if (
        sqlstate in ("08001", "08006", "08000")
        or "connection refused" in msg_lower
        or "could not connect to server" in msg_lower
        or "no route to host" in msg_lower
    ):
        cause = "Database server is unreachable or not accepting connections at the configured host and port."
        fix = "Ensure the PostgreSQL service is running and network/firewall settings allow connections."
        return cause, fix

    if sqlstate == "3D000" or (
        "does not exist" in msg_lower and "database" in msg_lower
    ):
        cause = "The specified database does not exist on the database server."
        fix = "Create the target database on the PostgreSQL server or update connection configuration."
        return cause, fix

    # 5. Missing relation / table
    if (
        sqlstate == "42P01"
        or "no such table:" in msg_lower
        or ("relation" in msg_lower and "does not exist" in msg_lower)
    ):
        cause = "Table or relation does not exist in the database schema."
        fix = "Verify the table name and run database schema migrations (init_schema) to create missing tables."
        return cause, fix

    # 6. Missing column
    if (
        sqlstate == "42703"
        or "no such column:" in msg_lower
        or ("column" in msg_lower and "does not exist" in msg_lower)
    ):
        cause = "Referenced column does not exist in the table schema."
        fix = "Verify column names against model definitions and apply pending database migrations."
        return cause, fix

    # 7. SQL Syntax / Invalid SQL
    if (
        sqlstate == "42601"
        or "syntax error" in msg_lower
        or "near " in msg_lower
        and "syntax error" in msg_lower
    ):
        cause = "SQL query contains syntax errors or invalid statements for the database dialect."
        fix = "Check the SQL statement syntax against the target database dialect."
        return cause, fix

    # 8. Integrity Constraints
    if (
        isinstance(exc, IntegrityError)
        or "constraint" in msg_lower
        or "duplicate" in msg_lower
        or "unique" in msg_lower
    ):
        # Unique violation
        if (
            sqlstate == "23505"
            or "unique constraint" in msg_lower
            or "unique" in msg_lower
            or "duplicate key" in msg_lower
        ):
            cause = "A unique constraint was violated; an entry with these values already exists."
            fix = "Verify that unique fields (e.g. PAN, folio number, email) are not duplicated, or update the existing record."
            return cause, fix

        # Foreign key violation
        if (
            sqlstate == "23503"
            or "foreign key" in msg_lower
            or "foreignkey" in msg_lower
        ):
            cause = "A foreign key constraint was violated; referenced parent entity does not exist or child records exist."
            fix = "Ensure the referenced entity exists before inserting, or delete dependent child records first."
            return cause, fix

        # NOT NULL violation
        if sqlstate == "23502" or "not null" in msg_lower or "notnull" in msg_lower:
            cause = "A NOT NULL constraint was violated; a required field value was missing or null."
            fix = "Provide valid non-null values for all required columns."
            return cause, fix

        # CHECK constraint violation
        if sqlstate == "23514" or "check constraint" in msg_lower:
            cause = "A CHECK constraint was violated; input value does not meet defined column rules."
            fix = "Verify that input values meet defined column validation rules and constraints."
            return cause, fix

        cause = f"Database integrity constraint violated: {orig_msg}"
        fix = "Ensure input values satisfy all unique, foreign key, and check constraints."
        return cause, fix

    # 9. Data Error / Range / Type mismatch
    if (
        isinstance(exc, DataError)
        or (sqlstate and sqlstate.startswith("22"))
        or "datatype mismatch" in msg_lower
    ):
        cause = "Invalid or out-of-range data value provided for database column."
        fix = "Verify input data types, string lengths, and formats match the database schema."
        return cause, fix

    # 10. InterfaceError (driver usage)
    if isinstance(exc, InterfaceError):
        cause = f"Database driver interface error: {orig_msg}"
        fix = "Verify database driver configuration, connection state, and parameters."
        return cause, fix

    # 11. Generic OperationalError
    if isinstance(exc, OperationalError):
        cause = f"Database operational failure: {orig_msg}"
        fix = "Verify database server status, network connectivity, and transaction state."
        return cause, fix

    # 12. Generic / Unknown Error
    cause = f"Database operation failed: {orig_msg}"
    fix = "Inspect the original error details and database server logs for troubleshooting."
    return cause, fix


def clean_original_error(exc: BaseException) -> str:
    """Extract clean original error message without SQL parameter dumps or URLs."""
    orig = getattr(exc, "orig", None)
    if orig is not None:
        raw = str(orig).strip()
    else:
        # Check cause
        cause = getattr(exc, "__cause__", None)
        if cause is not None and str(cause).strip():
            raw = str(cause).strip()
        elif hasattr(exc, "_message") and callable(exc._message):
            raw = str(exc._message()).strip()
        else:
            raw = str(exc).strip()

    # Special handling for psycopg ProactorEventLoop long message
    if "Psycopg cannot use the 'ProactorEventLoop' to run in async mode." in raw:
        return "Psycopg cannot use the 'ProactorEventLoop' to run in async mode."

    cleaned = sanitize_message(raw)
    return cleaned or "Unknown driver error"


def analyze_db_error(
    exc: BaseException,
    backend: str | None = None,
    statement: Any | None = None,
    operation: str | None = None,
    location: str | None = None,
) -> DatabaseErrorInfo:
    """Inspect exception and context to construct a structured DatabaseErrorInfo."""
    # Determine original SQLAlchemy exception class
    orig_exc = exc
    if (
        not isinstance(exc, SQLAlchemyError)
        and getattr(exc, "__cause__", None)
        and isinstance(exc.__cause__, SQLAlchemyError)
    ):
        orig_exc = exc.__cause__

    module_name = orig_exc.__class__.__module__
    class_name = orig_exc.__class__.__qualname__
    if module_name.startswith("sqlalchemy."):
        exception_type = f"{module_name}.{class_name}"
    else:
        exception_type = (
            f"sqlalchemy.exc.{class_name}"
            if "sqlalchemy" in module_name
            else f"{module_name}.{class_name}"
        )

    detected_backend = detect_backend(exc=orig_exc, dialect_name=backend)
    detected_op, detected_query = detect_operation_and_query(
        exc=orig_exc,
        statement=statement,
        operation_hint=operation,
    )
    detected_location = location or extract_application_location(exc=orig_exc)
    orig_msg = clean_original_error(orig_exc)
    cause, fix = classify_cause_and_fix(orig_exc, detected_backend, orig_msg)

    return DatabaseErrorInfo(
        exception_type=exception_type,
        backend=detected_backend,
        operation=detected_op,
        query=detected_query,
        location=detected_location,
        cause=cause,
        fix=fix,
        original_error=orig_msg,
    )


def format_database_error(info: DatabaseErrorInfo) -> str:
    """Format DatabaseErrorInfo into the standardized, concise console error block."""
    lines: list[str] = [
        f"[DATABASE ERROR] {info.exception_type}",
        "",
        f"{'Backend':<10}: {info.backend}",
        f"{'Operation':<10}: {info.operation}",
        f"{'Query':<10}: {info.query or 'Not available'}",
        f"{'Location':<10}: {info.location}",
    ]

    # Multiline Cause formatting with 12-space indentation on continuation lines
    cause_lines = info.cause.splitlines()
    if cause_lines:
        lines.append(f"{'Cause':<10}: {cause_lines[0]}")
        for cl in cause_lines[1:]:
            lines.append(f"{' ' * 12}{cl}")
    else:
        lines.append(f"{'Cause':<10}: Unknown")

    # Multiline Fix formatting with 12-space indentation on continuation lines
    fix_lines = info.fix.splitlines()
    if fix_lines:
        lines.append(f"{'Fix':<10}: {fix_lines[0]}")
        for fl in fix_lines[1:]:
            lines.append(f"{' ' * 12}{fl}")
    else:
        lines.append(f"{'Fix':<10}: Unknown")

    lines.append("")
    lines.append("Original error:")
    orig_lines = info.original_error.splitlines()
    if orig_lines:
        lines.extend(orig_lines)
    else:
        lines.append("Unknown")

    return "\n".join(lines)


def report_database_error(
    exc: BaseException,
    backend: str | None = None,
    statement: Any | None = None,
    operation: str | None = None,
    location: str | None = None,
) -> DatabaseErrorInfo | None:
    """Analyze, format, and report database error to console once without duplication.

    Attaches `_folioman_db_error_reported = True` to the exception so it will not
    be reported multiple times across application abstraction layers.
    """
    if getattr(exc, "_folioman_db_error_reported", False):
        return getattr(exc, "_folioman_db_error_info", None)

    # Check if cause was already reported
    cause = getattr(exc, "__cause__", None)
    if cause is not None and getattr(cause, "_folioman_db_error_reported", False):
        info = getattr(cause, "_folioman_db_error_info", None)
        exc._folioman_db_error_reported = True
        if info:
            exc._folioman_db_error_info = info
        return info

    info = analyze_db_error(
        exc=exc,
        backend=backend,
        statement=statement,
        operation=operation,
        location=location,
    )

    formatted = format_database_error(info)

    # Output to stderr only if explicitly enabled via environment variable
    if os.environ.get("FOLIOMAN_DEBUG_DB_ERRORS") == "1":
        try:
            sys.stderr.write(formatted + "\n")
            sys.stderr.flush()
        except OSError:
            pass
    else:
        logger.debug("Database error diagnostic:\n%s", formatted)

    # Record marker on exception instance to prevent duplicates
    exc._folioman_db_error_reported = True
    exc._folioman_db_error_info = info

    # If cause exists, also mark cause
    if cause is not None:
        cause._folioman_db_error_reported = True
        cause._folioman_db_error_info = info

    return info


__all__ = [
    "DatabaseErrorInfo",
    "analyze_db_error",
    "classify_cause_and_fix",
    "clean_original_error",
    "detect_backend",
    "detect_operation_and_query",
    "extract_application_location",
    "format_database_error",
    "mask_pan",
    "report_database_error",
    "sanitize_message",
    "sanitize_query",
    "sanitize_url",
]
