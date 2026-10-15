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


def translate_integrity_error(exc: IntegrityError) -> Exception:
    """Analyze the DBAPI driver error to provide meaningful domain errors."""
    msg = str(exc.orig or exc).lower()

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
        return FoliomanDatabaseError(f"Duplicate entry error: {exc.orig or exc}")

    return FoliomanDatabaseError(
        f"Database integrity constraint violated: {exc.orig or exc}"
    )


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
        logger.warning("Database integrity violation: %s", exc)
        raise translate_integrity_error(exc) from exc

    except OperationalError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        logger.error("Database operational error (connection/lock): %s", exc)
        raise FoliomanDatabaseError(
            f"Database unavailable, timed out, or locked: {exc.orig or exc}"
        ) from exc

    except NoResultFound as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        raise FoliomanNotFoundError(f"Requested resource not found: {exc}") from exc

    except DBAPIError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        logger.error("DBAPI driver error: %s", exc)
        raise FoliomanDatabaseError(
            f"Database driver error: {exc.orig or exc}"
        ) from exc

    except SQLAlchemyError as exc:
        if session:
            try:
                await session.rollback()
            except Exception:
                pass
        logger.error("SQLAlchemy internal error: %s", exc)
        raise FoliomanDatabaseError(f"Database error: {exc}") from exc


__all__ = [
    "handle_db_errors",
    "translate_integrity_error",
]
