"""Tests for Folioman CAS import CLI commands."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from folioman_client.cli.main import cli
from folioman_client.config import settings
from folioman_client.core.cas_reader import ParsedCas
from folioman_client.core.models.cas import (
    CasInvestorIdentity,
    MfCasLineItem,
    MfCasSchemeBlock,
    MfCasStatement,
)
from folioman_client.core.models.investor import Folio as CoreFolio
from folioman_client.core.models.security import Security as CoreSecurity, SecurityType
from folioman_client.core.models.transaction import TransactionType
from folioman_client.core.parser import CASPasswordError


def test_cli_import_cas_success(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    db_file = tmp_path / "cli_import_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "database_url", db_url)

    pdf_file = tmp_path / "sample_cas.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 dummy CAS stream")

    sec = CoreSecurity(type=SecurityType.MF, name="Nippon India Small Cap", isin="INF204K01914", amfi_code="119598")
    fol = CoreFolio(folio_type="mf", number="555/0", amc_code="NIPPON")
    block = MfCasSchemeBlock(
        security=sec,
        folio=fol,
        opening_units=Decimal("0"),
        closing_units=Decimal("50"),
        transactions=[
            MfCasLineItem(
                date=date(2026, 2, 1),
                transaction_type=TransactionType.BUY,
                units=Decimal("50.0000"),
                nav=Decimal("120.0000"),
                amount=Decimal("6000.00"),
                description="Purchase",
            )
        ],
    )
    stmt = MfCasStatement(
        investor_name="Vikram Seth",
        investor_email="vikram@example.com",
        pan_masked="XXXXXX9999K",
        statement_from=date(2026, 2, 1),
        statement_to=date(2026, 2, 28),
        schemes=[block],
    )
    identity = CasInvestorIdentity(name="Vikram Seth", email="vikram@example.com", pan="ABCDE9999K")
    mock_parsed = ParsedCas(mf=stmt, investor=identity)

    with patch("folioman_client.services.import_service.read_cas", return_value=mock_parsed):
        res = runner.invoke(
            cli,
            ["--database-url", db_url, "import", "cas", str(pdf_file), "--password", "testpass"],
        )

    assert res.exit_code == 0
    assert "CAS Import Status: COMPLETED" in res.output
    assert "Vikram Seth" in res.output
    assert "Schemes Processed:      1" in res.output
    assert "Transactions Created:   1" in res.output


def test_cli_import_cas_wrong_password(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    db_file = tmp_path / "cli_err_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "database_url", db_url)

    pdf_file = tmp_path / "locked.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 locked stream")

    with patch("folioman_client.services.import_service.read_cas", side_effect=CASPasswordError("Incorrect PDF password")):
        res = runner.invoke(
            cli,
            ["--database-url", db_url, "import", "cas", str(pdf_file), "--password", "wrongpass"],
        )

    assert res.exit_code != 0
    assert "Import failed" in res.output
