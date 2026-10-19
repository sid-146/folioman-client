"""Tests for nav CLI subcommands."""

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from folioman_client.cli.main import cli


def test_cli_navs_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["navs", "--help"])
    assert result.exit_code == 0
    assert "Manage mutual fund NAVs and market closing prices." in result.output
    assert "refresh" in result.output
    assert "backfill" in result.output
    assert "status" in result.output


def test_cli_navs_refresh():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.nav.NAVService.refresh_navs",
        new_callable=AsyncMock,
        return_value={"updated": 5, "skipped": 1, "errors": 0},
    ) as mock_refresh:
        result = runner.invoke(cli, ["navs", "refresh", "--types", "mf,equity"])
        assert result.exit_code == 0
        assert "Refreshing latest NAVs and market prices..." in result.output
        assert "Updated: 5" in result.output
        assert "Skipped: 1" in result.output
        assert "Errors:  0" in result.output
        mock_refresh.assert_awaited_once_with(types=["mf", "equity"])


def test_cli_navs_backfill():
    runner = CliRunner()
    with patch(
        "folioman_client.cli.nav.NAVService.backfill_navs",
        new_callable=AsyncMock,
        return_value={
            "securities": 2,
            "points": 150,
            "skipped": 0,
            "closed": 0,
            "errors": 0,
        },
    ) as mock_backfill:
        result = runner.invoke(
            cli, ["navs", "backfill", "--force", "--security-id", "12"]
        )
        assert result.exit_code == 0
        assert "Backfilling NAV history (forced full scan)..." in result.output
        assert "Securities Updated: 2" in result.output
        assert "Data Points Added:  150" in result.output
        mock_backfill.assert_awaited_once_with(security_id=12, force=True)


def test_cli_navs_status():
    runner = CliRunner()
    mock_freshness = {
        "as_of": "2026-04-10",
        "last_refreshed_at": "2026-04-10 18:30:00",
        "next_refresh_at": "2026-04-11 04:00:00",
        "securities": [
            {
                "security_id": 1,
                "name": "Parag Parikh Flexi Cap Fund",
                "security_type": "mf",
                "identifier": "122639",
                "feed_code": "122639",
                "latest_nav_date": "2026-04-10",
                "first_nav_date": "2020-01-01",
                "points": 1500,
                "lag_trading_days": 0,
                "status": "fresh",
            }
        ],
    }
    with patch(
        "folioman_client.cli.nav.NAVService.get_nav_freshness",
        new_callable=AsyncMock,
        return_value=mock_freshness,
    ):
        result = runner.invoke(cli, ["navs", "status"])
        assert result.exit_code == 0
        assert "Folioman NAV Freshness & Price Feed Status" in result.output
        assert "As-Of Trading Day:     2026-04-10" in result.output
        assert "Parag Parikh Flexi Cap Fund" in result.output
        assert "fresh" in result.output
