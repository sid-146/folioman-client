"""Tests for SQLAlchemy database error translation and handling."""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner
from sqlalchemy.exc import (
    DBAPIError,
    IntegrityError,
    NoResultFound,
    OperationalError,
    SQLAlchemyError,
)

from folioman_client.cli.main import cli
from folioman_client.db import create_folioman_engine, handle_db_errors, init_schema
from folioman_client.db.errors import translate_integrity_error
from folioman_client.errors import (
    DuplicateInvestorError,
    FoliomanDatabaseError,
    FoliomanNotFoundError,
)
from folioman_client.services.ledger_service import LedgerService


def test_translate_integrity_error():
    # Investor PAN duplicate
    exc_pan = IntegrityError(
        "INSERT ...",
        {},
        sqlite3.IntegrityError(
            "UNIQUE constraint failed: investors.user_id, investors.pan_hash"
        ),
    )
    trans_pan = translate_integrity_error(exc_pan)
    assert isinstance(trans_pan, DuplicateInvestorError)
    assert "already exists" in str(trans_pan)

    # Named constraint uniq_investor_user_pan
    exc_pan_named = IntegrityError(
        "INSERT ...",
        {},
        Exception('violates unique constraint "uniq_investor_user_pan"'),
    )
    assert isinstance(translate_integrity_error(exc_pan_named), DuplicateInvestorError)

    # Folio unique constraint
    exc_folio = IntegrityError(
        "INSERT ...",
        {},
        Exception('violates unique constraint "uniq_folio_inv_number_amc"'),
    )
    trans_folio = translate_integrity_error(exc_folio)
    assert isinstance(trans_folio, FoliomanDatabaseError)
    assert "folio with this number" in str(trans_folio)

    # Family unique constraint
    exc_family = IntegrityError(
        "INSERT ...",
        {},
        Exception('violates unique constraint "uniq_family_user_name"'),
    )
    trans_family = translate_integrity_error(exc_family)
    assert isinstance(trans_family, FoliomanDatabaseError)
    assert "family group with this name" in str(trans_family)

    # NAV history unique constraint
    exc_nav = IntegrityError(
        "INSERT ...",
        {},
        Exception('violates unique constraint "uniq_nav_security_date"'),
    )
    trans_nav = translate_integrity_error(exc_nav)
    assert isinstance(trans_nav, FoliomanDatabaseError)
    assert "NAV for this security" in str(trans_nav)

    # Foreign key constraint
    exc_fk = IntegrityError(
        "INSERT ...", {}, sqlite3.IntegrityError("FOREIGN KEY constraint failed")
    )
    trans_fk = translate_integrity_error(exc_fk)
    assert isinstance(trans_fk, FoliomanDatabaseError)
    assert "Foreign key constraint violation" in str(trans_fk)

    # Generic unique constraint
    exc_gen = IntegrityError("INSERT ...", {}, Exception("unique constraint violation"))
    trans_gen = translate_integrity_error(exc_gen)
    assert isinstance(trans_gen, FoliomanDatabaseError)
    assert "Duplicate entry error" in str(trans_gen)


@pytest.mark.asyncio
async def test_handle_db_errors_rollbacks_and_translates():
    mock_session = AsyncMock()

    # OperationalError
    with pytest.raises(FoliomanDatabaseError, match="Database unavailable"):
        async with handle_db_errors(mock_session):
            raise OperationalError("SELECT ...", {}, Exception("database is locked"))
    assert mock_session.rollback.await_count == 1

    # NoResultFound
    with pytest.raises(FoliomanNotFoundError, match="Requested resource not found"):
        async with handle_db_errors(mock_session):
            raise NoResultFound("No row was found when one was required")

    # DBAPIError
    with pytest.raises(FoliomanDatabaseError, match="Database driver error"):
        async with handle_db_errors(mock_session):
            raise DBAPIError("SELECT ...", {}, Exception("low-level driver crash"))

    # Generic SQLAlchemyError
    with pytest.raises(FoliomanDatabaseError, match="Database error"):
        async with handle_db_errors(mock_session):
            raise SQLAlchemyError("internal orm error")


@pytest.mark.asyncio
async def test_ledger_service_duplicate_investor_raises_duplicate_error():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = LedgerService(engine=engine)

    try:
        # Create first investor
        inv1 = await service.create_investor(
            user_id="advisor_1",
            name="Rohit Sharma",
            pan="ABCDE1111R",
        )
        assert inv1["name"] == "Rohit Sharma"

        # Create second investor with same PAN under same user -> must raise DuplicateInvestorError
        with pytest.raises(DuplicateInvestorError, match="already exists"):
            await service.create_investor(
                user_id="advisor_1",
                name="Rohit Sharma Duplicate",
                pan="ABCDE1111R",
            )

        # But a different user can have the same PAN
        inv2 = await service.create_investor(
            user_id="advisor_2",
            name="Rohit Sharma Under Advisor 2",
            pan="ABCDE1111R",
        )
        assert inv2["name"] == "Rohit Sharma Under Advisor 2"

        # Investors with empty PAN can be created multiple times for the same user
        inv_no_pan1 = await service.create_investor(
            user_id="advisor_1",
            name="No PAN 1",
            pan="",
        )
        inv_no_pan2 = await service.create_investor(
            user_id="advisor_1",
            name="No PAN 2",
            pan="",
        )
        assert inv_no_pan1["id"] != inv_no_pan2["id"]
    finally:
        await engine.dispose()


def test_cli_create_investor_duplicate_pan_graceful_exit():
    runner = CliRunner()
    from unittest.mock import patch

    with patch(
        "folioman_client.cli.ledger.LedgerService.create_investor",
        side_effect=DuplicateInvestorError(
            "An investor with this PAN already exists for this user."
        ),
    ):
        res = runner.invoke(
            cli, ["investors", "create", "-n", "Dup Test", "-p", "ABCDE1234F"]
        )
        assert res.exit_code != 0
        assert "Error: An investor with this PAN already exists" in res.output
