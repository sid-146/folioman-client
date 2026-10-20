"""Unit tests for Phase 6 CLI subcommands: portfolio, valuations, and capital-gains."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from folioman_client.cli.main import cli


def test_cli_portfolio_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["portfolio", "--help"])
    assert result.exit_code == 0
    assert (
        "Query portfolio summaries, valuations, and performance metrics."
        in result.output
    )
    assert "summary" in result.output


def test_cli_portfolio_summary():
    runner = CliRunner()
    mock_summary = {
        "as_of": date(2024, 6, 1),
        "total_inr": Decimal("150000.50"),
        "day_change_inr": Decimal("1250.00"),
        "xirr": 0.1425,
        "holdings_count": 5,
        "tax_ready_count": 4,
        "integrity_unit_count": 4,
        "asset_mix": [
            {"security_type": "mf", "value_inr": Decimal("100000.00")},
            {"security_type": "equity", "value_inr": Decimal("50000.50")},
        ],
        "top_holdings": [
            {
                "name": "HDFC Top 100",
                "units": Decimal(500),
                "value_inr": Decimal("100000.00"),
                "return_pct": 0.25,
            }
        ],
        "period_returns": [{"period": "1Y", "annualized": 0.15, "absolute": 0.15}],
    }
    with patch(
        "folioman_client.cli.portfolio.ValuationService.build_investor_summary",
        new_callable=AsyncMock,
        return_value=mock_summary,
    ) as mock_build:
        result = runner.invoke(cli, ["portfolio", "summary", "-i", "10"])
        assert result.exit_code == 0
        assert "Portfolio Summary for Investor ID: 10" in result.output
        assert "INR 150,000.50" in result.output
        assert "14.25%" in result.output
        assert "HDFC Top 100" in result.output
        assert "1Y" in result.output
        mock_build.assert_awaited_once_with(10, as_of=None)


def test_cli_valuations_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["valuations", "--help"])
    assert result.exit_code == 0
    assert (
        "Manage daily valuation series, status checks, and recompute ticks."
        in result.output
    )
    assert "status" in result.output
    assert "series" in result.output
    assert "tick" in result.output


def test_cli_valuations_status_investor():
    runner = CliRunner()
    mock_st = {
        "investor_id": 5,
        "status": "ready",
        "computed_through": date(2024, 6, 1),
        "recompute_from": None,
        "is_provisional": False,
    }
    with patch(
        "folioman_client.cli.valuations.ValuationService.get_valuation_status",
        new_callable=AsyncMock,
        return_value=mock_st,
    ) as mock_status:
        result = runner.invoke(cli, ["valuations", "status", "-i", "5"])
        assert result.exit_code == 0
        assert "Investor ID:      5" in result.output
        assert "Status:           READY" in result.output
        assert "Computed Through: 2024-06-01" in result.output
        mock_status.assert_awaited_once_with(5)


def test_cli_valuations_status_family():
    runner = CliRunner()
    mock_st = {
        "family_id": 2,
        "status": "ready",
        "computed_through": date(2024, 6, 1),
        "is_provisional": False,
    }
    with patch(
        "folioman_client.cli.valuations.ValuationService.get_family_valuation_status",
        new_callable=AsyncMock,
        return_value=mock_st,
    ) as mock_fam_status:
        result = runner.invoke(cli, ["valuations", "status", "-f", "2"])
        assert result.exit_code == 0
        assert "Family ID:        2" in result.output
        assert "Status:           READY" in result.output
        mock_fam_status.assert_awaited_once_with(2)


def test_cli_valuations_series():
    runner = CliRunner()
    mock_series = {
        "investor_id": 7,
        "points": [
            {
                "date": date(2024, 1, 1),
                "value_inr": Decimal(50000),
                "invested_inr": Decimal(40000),
                "stale": False,
            },
            {
                "date": date(2024, 2, 1),
                "value_inr": Decimal(52000),
                "invested_inr": Decimal(40000),
                "stale": True,
            },
        ],
    }
    with patch(
        "folioman_client.cli.valuations.ValuationService.value_series",
        new_callable=AsyncMock,
        return_value=mock_series,
    ) as mock_val_series:
        result = runner.invoke(
            cli, ["valuations", "series", "-i", "7", "-g", "monthly"]
        )
        assert result.exit_code == 0
        assert "Net-Worth Series for Investor 7 (Monthly):" in result.output
        assert "2024-01-01" in result.output
        assert "50,000.00" in result.output
        assert "YES" in result.output
        mock_val_series.assert_awaited_once_with(
            7, from_date=None, to_date=None, granularity="monthly"
        )


def test_cli_valuations_tick():
    runner = CliRunner()
    with (
        patch(
            "folioman_client.cli.valuations.ValuationService.process_pending_valuations",
            new_callable=AsyncMock,
            return_value=3,
        ) as mock_proc,
        patch(
            "folioman_client.cli.valuations.ValuationService.enqueue_daily_extend",
            new_callable=AsyncMock,
            return_value=5,
        ) as mock_ext,
    ):
        # Tick pending
        res_p = runner.invoke(cli, ["valuations", "tick", "--pending"])
        assert res_p.exit_code == 0
        assert "Processed 3 pending valuations." in res_p.output
        mock_proc.assert_awaited_once()

        # Tick extend
        res_e = runner.invoke(cli, ["valuations", "tick", "--extend"])
        assert res_e.exit_code == 0
        assert "Queued 5 investors for daily extension." in res_e.output
        mock_ext.assert_awaited_once()


def test_cli_capital_gains_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["capital-gains", "--help"])
    assert result.exit_code == 0
    assert (
        "Compute and report realized capital gains (STCG/LTCG) and Schedule 112A."
        in result.output
    )
    assert "list" in result.output
    assert "report" in result.output


def test_cli_capital_gains_list():
    runner = CliRunner()
    mock_fys = [
        {"fy": "2023-24", "stcg": Decimal("15000.00"), "ltcg": Decimal("30000.00")},
        {"fy": "2024-25", "stcg": Decimal("5000.00"), "ltcg": Decimal("45000.00")},
    ]
    with patch(
        "folioman_client.cli.capital_gains.CapitalGainsService.list_capital_gains_by_fy",
        new_callable=AsyncMock,
        return_value=mock_fys,
    ) as mock_list:
        result = runner.invoke(cli, ["capital-gains", "list", "-i", "1"])
        assert result.exit_code == 0
        assert (
            "Realized Capital Gains by Financial Year for Investor 1:" in result.output
        )
        assert "2023-24" in result.output
        assert "15,000.00" in result.output
        assert "30,000.00" in result.output
        assert "45,000.00" in result.output
        mock_list.assert_awaited_once_with(1, include_unreconciled=False)


def test_cli_capital_gains_report_with_csv(tmp_path):
    runner = CliRunner()
    mock_rep = {
        "fy": "2024-25",
        "stcg_total": Decimal("2000.00"),
        "ltcg_total": Decimal("10000.00"),
        "exempt_total": Decimal("0.00"),
        "rows": [
            {
                "name": "Tata Motors",
                "units": Decimal(100),
                "term": "long",
                "acquired_on": date(2020, 1, 1),
                "sold_on": date(2024, 5, 1),
                "sale_value": Decimal("50000.00"),
                "cost": Decimal("40000.00"),
                "gain": Decimal("10000.00"),
                "grandfathering_unavailable": False,
            }
        ],
    }
    mock_s112a = {
        "fy": "2024-25",
        "row_count": 1,
        "columns": [
            "ISIN Code(2)",
            "Name of the Share/Unit(3)",
            "Balance(14) = 6 - 13",
        ],
        "rows": [
            {
                "ISIN Code(2)": "INE155A01022",
                "Name of the Share/Unit(3)": "Tata Motors",
                "Balance(14) = 6 - 13": "10000.00",
            }
        ],
    }
    csv_file = tmp_path / "schedule112a.csv"

    with (
        patch(
            "folioman_client.cli.capital_gains.CapitalGainsService.get_capital_gains_report",
            new_callable=AsyncMock,
            return_value=mock_rep,
        ) as mock_report,
        patch(
            "folioman_client.cli.capital_gains.CapitalGainsService.get_schedule_112a",
            new_callable=AsyncMock,
            return_value=mock_s112a,
        ) as mock_csv,
    ):
        result = runner.invoke(
            cli,
            [
                "capital-gains",
                "report",
                "-i",
                "1",
                "--fy",
                "2024-25",
                "--csv",
                str(csv_file),
            ],
        )
        assert result.exit_code == 0
        assert "Capital Gains Report: Investor 1 (FY 2024-25)" in result.output
        assert "Tata Motors" in result.output
        assert "10,000.00" in result.output
        assert f"Exporting official Schedule 112A CSV to {csv_file!s}" in result.output
        assert f"Successfully exported 1 rows to {csv_file!s}" in result.output
        mock_report.assert_awaited_once_with(1, "2024-25", include_unreconciled=False)
        mock_csv.assert_awaited_once_with(1, "2024-25", include_unreconciled=False)

        assert csv_file.exists()
        content = csv_file.read_text(encoding="utf-8")
        assert "INE155A01022" in content
