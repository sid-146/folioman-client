"""Tests for Phase 5 CLI subcommands: reconcile, symbols, corporate-actions, and ledger."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from click.testing import CliRunner

from folioman_client.cli.main import cli


def test_cli_reconcile_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["reconcile", "--help"])
    assert result.exit_code == 0
    assert "Reconcile trade ledgers against reported statement holdings." in result.output
    assert "all" in result.output
    assert "acknowledge" in result.output
    assert "clear" in result.output


def test_cli_reconcile_all_global():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.reconcile.ReconciliationService.reconcile_all",
        new_callable=AsyncMock,
        return_value={
            "investors_count": 3,
            "statuses_count": 12,
            "tax_safe_count": 10,
            "mismatch_count": 2,
        },
    ) as mock_all:
        result = runner.invoke(cli, ["reconcile", "all"])
        assert result.exit_code == 0
        assert "Reconciling positions across all investors..." in result.output
        assert "Investors:          3" in result.output
        assert "Folio Positions:    12" in result.output
        assert "Tax-Safe Positions: 10" in result.output
        assert "Mismatches:         2" in result.output
        mock_all.assert_awaited_once()


def test_cli_reconcile_all_single_investor():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.reconcile.ReconciliationService.reconcile_investor",
        new_callable=AsyncMock,
        return_value={
            "investor_id": 42,
            "securities_reconciled": 5,
            "statuses_count": 5,
            "tax_safe_count": 5,
            "mismatch_count": 0,
        },
    ) as mock_inv:
        result = runner.invoke(cli, ["reconcile", "all", "--investor-id", "42"])
        assert result.exit_code == 0
        assert "Reconciling positions for investor 42..." in result.output
        assert "Securities Reconciled: 5" in result.output
        mock_inv.assert_awaited_once_with(42)


def test_cli_reconcile_acknowledge_and_clear():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.reconcile.ReconciliationService.acknowledge_mismatch",
        new_callable=AsyncMock,
        return_value={"status": "user_acknowledged", "tax_safe": True, "issues": []},
    ) as mock_ack:
        res_ack = runner.invoke(
            cli,
            ["reconcile", "acknowledge", "-i", "1", "-s", "2", "-f", "3"],
        )
        assert res_ack.exit_code == 0
        assert "Updated Status: user_acknowledged" in res_ack.output
        mock_ack.assert_awaited_once_with(1, 2, 3)

    with patch(
        "folioman_client.cli.reconcile.ReconciliationService.clear_acknowledgement",
        new_callable=AsyncMock,
        return_value={"status": "mismatch", "tax_safe": False, "issues": []},
    ) as mock_clear:
        res_clear = runner.invoke(
            cli,
            ["reconcile", "clear", "-i", "1", "-s", "2", "-f", "3"],
        )
        assert res_clear.exit_code == 0
        assert "Restored Status: mismatch" in res_clear.output
        mock_clear.assert_awaited_once_with(1, 2, 3)


def test_cli_symbols_resolve():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.symbols.EquitySymbolService.resolve_symbols",
        new_callable=AsyncMock,
        return_value={
            "unresolved_count": 2,
            "matched_count": 1,
            "updated_count": 1,
            "unmatched_count": 1,
            "matched": [
                {
                    "id": 10,
                    "name": "Tata Motors",
                    "isin": "INE155A01022",
                    "symbol": "TATAMOTORS",
                    "exchange": "NSE",
                }
            ],
            "unmatched": [{"id": 11, "name": "Unknown", "isin": "INE999X01099"}],
            "backfill": {"securities": 1, "points": 100},
        },
    ) as mock_resolve:
        result = runner.invoke(cli, ["symbols", "resolve", "--backfill"])
        assert result.exit_code == 0
        assert "Unresolved Securities: 2" in result.output
        assert "Symbols Matched:       1" in result.output
        assert "INE155A01022 -> TATAMOTORS (NSE)" in result.output
        assert "INE999X01099" in result.output
        assert "Points:     100" in result.output
        mock_resolve.assert_awaited_once_with(
            dry_run=False, backfill=True, force_backfill=False
        )


def test_cli_corporate_actions_commands():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.corporate_actions.CorporateActionService.refresh_corporate_actions",
        new_callable=AsyncMock,
        return_value={"securities_checked": 5, "actions_fetched": 12, "errors": 0},
    ) as mock_refresh:
        res = runner.invoke(cli, ["corporate-actions", "refresh", "--since-year", "2020"])
        assert res.exit_code == 0
        assert "Securities Checked: 5" in res.output
        assert "Actions Fetched:    12" in res.output
        mock_refresh.assert_awaited_once_with(security_ids=None, since_year=2020)

    with patch(
        "folioman_client.cli.corporate_actions.CorporateActionService.list_references",
        new_callable=AsyncMock,
        return_value=[
            {
                "id": 1,
                "isin": "INE002A01018",
                "symbol": "RELIANCE",
                "ex_date": "2024-10-28",
                "type": "bonus",
                "unit_multiplier": "2",
                "subject": "Bonus 1:1",
            }
        ],
    ) as mock_list:
        res_list = runner.invoke(cli, ["corporate-actions", "list", "--symbol", "RELIANCE"])
        assert res_list.exit_code == 0
        assert "RELIANCE" in res_list.output
        assert "Bonus 1:1" in res_list.output

    with patch(
        "folioman_client.cli.corporate_actions.CorporateActionService.apply_corporate_action",
        new_callable=AsyncMock,
        return_value={
            "applied": True,
            "kind": "bonus",
            "unit_multiplier": "2",
            "ex_date": "2024-10-28",
        },
    ) as mock_apply:
        res_apply = runner.invoke(
            cli,
            ["corporate-actions", "apply", "-i", "1", "-f", "2", "-r", "1"],
        )
        assert res_apply.exit_code == 0
        assert "Successfully applied bonus" in res_apply.output


def test_cli_investors_commands():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.ledger.LedgerService.list_investors",
        new_callable=AsyncMock,
        return_value=[
            {
                "id": 1,
                "name": "Hardik Pandya",
                "pan_masked": "XXXXXX999H",
                "email": "hardik@example.com",
            }
        ],
    ) as mock_list:
        res = runner.invoke(cli, ["investors", "list"])
        assert res.exit_code == 0
        assert "Hardik Pandya" in res.output
        assert "XXXXXX999H" in res.output

    with patch(
        "folioman_client.cli.ledger.LedgerService.create_investor",
        new_callable=AsyncMock,
        return_value={"id": 2, "name": "Krunal Pandya", "pan_masked": "XXXXXX888K"},
    ) as mock_create:
        res_create = runner.invoke(
            cli, ["investors", "create", "-n", "Krunal Pandya", "-p", "ABCDE8888K"]
        )
        assert res_create.exit_code == 0
        assert "Created investor Krunal Pandya (ID: 2" in res_create.output


def test_cli_folios_commands():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.ledger.LedgerService.list_folios",
        new_callable=AsyncMock,
        return_value=[
            {
                "id": 5,
                "number": "12345/6",
                "amc_code": "HDFC",
                "folio_type": "mf",
                "broker": "ARN-0001",
            }
        ],
    ) as mock_list:
        res = runner.invoke(cli, ["folios", "list", "-i", "1"])
        assert res.exit_code == 0
        assert "12345/6" in res.output
        assert "HDFC" in res.output

    with patch(
        "folioman_client.cli.ledger.LedgerService.merge_folios",
        new_callable=AsyncMock,
        return_value={"transactions_moved": 4, "holdings_moved": 1},
    ) as mock_merge:
        res_merge = runner.invoke(
            cli, ["folios", "merge", "-i", "1", "-s", "5", "-t", "6"]
        )
        assert res_merge.exit_code == 0
        assert "Merge complete: 4 transactions and 1 holdings moved." in res_merge.output


def test_cli_transactions_and_holdings_commands():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.ledger.LedgerService.list_transactions",
        new_callable=AsyncMock,
        return_value=[
            {
                "id": 101,
                "date": "2025-01-10",
                "type": "BUY",
                "units": "50.0",
                "nav": "100.0",
                "amount": "5000.0",
                "security_name": "HDFC Top 100 Fund",
            }
        ],
    ) as mock_txns:
        res_txns = runner.invoke(cli, ["transactions", "list", "-i", "1"])
        assert res_txns.exit_code == 0
        assert "HDFC Top 100 Fund" in res_txns.output
        assert "5000.0" in res_txns.output

    with patch(
        "folioman_client.cli.ledger.LedgerService.list_holdings",
        new_callable=AsyncMock,
        return_value=[
            {
                "security_id": 20,
                "name": "Reliance Industries",
                "type": "EQUITY",
                "units": "100.0",
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
            }
        ],
    ) as mock_holds:
        res_holds = runner.invoke(cli, ["holdings", "list", "-i", "1"])
        assert res_holds.exit_code == 0
        assert "Reliance Industries" in res_holds.output
        assert "100.0" in res_holds.output
