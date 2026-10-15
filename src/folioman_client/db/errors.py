"""Database error translation utilities for SQLAlchemy."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    NoResultFound,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from folioman_client.errors import (
    DuplicateInvestorError,
    FoliomanDatabaseError,
    FoliomanNotFoundError,
)

logger = logging.getLogger(__name__)


def _clean_orig_message(exc: SQLAlchemyError) -> str:
    """Extract a clean driver message without SQL statements or bind parameters."""
    if hasattr(exc, "orig") and exc.orig is not None:
        return str(exc.orig).strip()
    # If no orig, take only the first line of str(exc) to prevent leaking SQL and bind parameters
    first_line = str(exc).split("\n")[0].strip()
    return first_line or "Database constraint violation"


def translate_integrity_error(exc: IntegrityError) -> Exception:
    """Analyze the DBAPI driver error to provide meaningful domain errors."""
    orig_msg = _clean_orig_message(exc)
    msg = orig_msg.lower()

    # Match investor user_id + pan_hash unique constraint
    if "uniq_investor_user_pan" in msg or ("investors" in msg and "pan" in msg):
        return DuplicateInvestorError(
            "An investor with this PAN already exists for this user."
        )

    # Match folio unique constraint
    if "uniq_folio_inv_number_amc" in msg:
        return FoliomanDatabaseError(
            "A folio with this number and AMC already exists for this investor."
        )

    # Match family unique constraint
    if "uniq_family_user_name" in msg:
        return FoliomanDatabaseError(
            "A family group with this name already exists for this user."
        )

    # Match NAV history unique constraint
    if "uniq_nav_security_date" in msg:
        return FoliomanDatabaseError("NAV for this security and date already exists.")

    # Foreign key constraint violations
    if "foreign key" in msg or "foreignkey" in msg:
        return FoliomanDatabaseError(
            "Foreign key constraint violation: referenced entity does not exist."
        )

    # General unique constraint violation
    if "unique constraint" in msg or "unique" in msg or "duplicate" in msg:
        return FoliomanDatabaseError(f"Duplicate entry error: {orig_msg}")

    return FoliomanDatabaseError(f"Database integrity constraint violated: {orig_msg}")


@asynccontextmanager
async def handle_db_errors(
    session: AsyncSession | None = None,
) -> AsyncIterator[None]:
    """Context manager to intercept SQLAlchemy exceptions, roll back, and raise domain errors.

    Args:
        session: Optional active AsyncSession. If provided, session.rollback() will be called on error.
    """
    try:
        yield
    except IntegrityError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        orig_msg = _clean_orig_message(exc)
        logger.debug("Database integrity constraint violated: %s", orig_msg)
        raise translate_integrity_error(exc) from None

    except OperationalError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        orig_msg = _clean_orig_message(exc)
        logger.error("Database operational error: %s", orig_msg)
        raise FoliomanDatabaseError(
            f"Database unavailable, timed out, or locked: {orig_msg}"
        ) from None

    except NoResultFound as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        raise FoliomanNotFoundError(f"Requested resource not found: {exc}") from None

    except DBAPIError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        orig_msg = _clean_orig_message(exc)
        logger.error("DBAPI driver error: %s", orig_msg)
        raise FoliomanDatabaseError(f"Database driver error: {orig_msg}") from None

    except SQLAlchemyError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        logger.error("Database error occurred: %s", type(exc).__name__)
        raise FoliomanDatabaseError(f"Database error: {type(exc).__name__}") from None


__all__ = [
    "handle_db_errors",
    "translate_integrity_error",
]
