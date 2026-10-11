"""Tests for core CAS parsing, charge pairing, folio normalization, and gap checking."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import pytest

from folioman_client.core.models.cas import (
    MfCasLineItem,
    MfCasSchemeBlock,
    MfCasStatement,
)
from folioman_client.core.models.investor import Folio as CoreFolio, normalize_folio_number
from folioman_client.core.models.security import Security as CoreSecurity, SecurityType
from folioman_client.core.models.transaction import TransactionType
from folioman_client.core.parser import _HISTORY_TOLERANCE, scheme_history_gap


def test_normalize_folio_number() -> None:
    # Trailing /0 or /00 default sub-account dropped
    assert normalize_folio_number("1234567/0") == "1234567"
    assert normalize_folio_number("1234567 / 0") == "1234567"
    assert normalize_folio_number("1234567/00") == "1234567"
    assert normalize_folio_number("1234567") == "1234567"
    assert normalize_folio_number(" 1234567 ") == "1234567"

    # Non-zero sub-account preserved
    assert normalize_folio_number("1234567/63") == "1234567/63"
    assert normalize_folio_number("1234567 / 1") == "1234567/1"


def test_scheme_history_gap_complete_history() -> None:
    security = CoreSecurity(type=SecurityType.MF, name="PPFAS Flexi Cap", isin="INF879O01019")
    folio = CoreFolio(folio_type="mf", number="1001/0")
    block = MfCasSchemeBlock(
        security=security,
        folio=folio,
        opening_units=Decimal("0"),
        closing_units=Decimal("100"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("100"),
                nav=Decimal("50"),
                amount=Decimal("5000"),
            )
        ],
    )
    # Zero opening balance with zero prior ledger chains cleanly
    assert scheme_history_gap(block, prior_balance=Decimal("0")) is None


def test_scheme_history_gap_opening_nonzero() -> None:
    security = CoreSecurity(type=SecurityType.MF, name="PPFAS Flexi Cap", isin="INF879O01019")
    folio = CoreFolio(folio_type="mf", number="1001")
    block = MfCasSchemeBlock(
        security=security,
        folio=folio,
        opening_units=Decimal("50"),
        closing_units=Decimal("150"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("100"),
                nav=Decimal("50"),
                amount=Decimal("5000"),
            )
        ],
    )
    # Non-zero opening balance when prior ledger is zero -> opening_nonzero
    assert scheme_history_gap(block, prior_balance=Decimal("0")) == "opening_nonzero"


def test_scheme_history_gap_mismatch() -> None:
    security = CoreSecurity(type=SecurityType.MF, name="PPFAS Flexi Cap", isin="INF879O01019")
    folio = CoreFolio(folio_type="mf", number="1001")
    block = MfCasSchemeBlock(
        security=security,
        folio=folio,
        opening_units=Decimal("50"),
        closing_units=Decimal("150"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("100"),
                nav=Decimal("50"),
                amount=Decimal("5000"),
            )
        ],
    )
    # Prior ledger has 30 units, but statement says opening is 50 -> history_gap
    assert scheme_history_gap(block, prior_balance=Decimal("30")) == "history_gap"


def test_scheme_history_gap_rows_unreconciled() -> None:
    security = CoreSecurity(type=SecurityType.MF, name="PPFAS Flexi Cap", isin="INF879O01019")
    folio = CoreFolio(folio_type="mf", number="1001")
    block = MfCasSchemeBlock(
        security=security,
        folio=folio,
        opening_units=Decimal("0"),
        closing_units=Decimal("150"),  # Expected 150
        transactions=[
            MfCasLineItem(
                date=date(2026, 1, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("100"),  # Only adds 100 -> opening + net = 100 != 150
                nav=Decimal("50"),
                amount=Decimal("5000"),
            )
        ],
    )
    assert scheme_history_gap(block, prior_balance=Decimal("0")) == "rows_unreconciled"
