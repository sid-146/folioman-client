"""Tests for FoliomanScheduler and scheduler CLI commands."""

from unittest.mock import AsyncMock, MagicMock, patch
from click.testing import CliRunner
import pytest

from folioman_client.cli.main import cli
from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.services.scheduler import FoliomanScheduler


@pytest.fixture
async def test_engine():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    yield engine
    await engine.dispose()


def test_scheduler_lifecycle(test_engine):
    scheduler = FoliomanScheduler(engine=test_engine)
    assert not scheduler.is_running

    scheduler.start(blocking=False)
    assert scheduler.is_running

    scheduler.shutdown()
    assert not scheduler.is_running


def test_scheduler_trigger_jobs(test_engine):
    scheduler = FoliomanScheduler(engine=test_engine)

    with (
        patch(
            "folioman_client.services.nav_service.NAVService.refresh_navs",
            new_callable=AsyncMock,
            return_value={"updated": 2, "skipped": 0, "errors": 0},
        ),
        patch(
            "folioman_client.services.nav_service.NAVService.backfill_navs",
            new_callable=AsyncMock,
            return_value={"securities": 1, "points": 10, "skipped": 0, "closed": 0, "errors": 0},
        ),
        patch(
            "folioman_client.services.isin_service.ISINService.update_reference_data",
            new_callable=AsyncMock,
            return_value={"updated": True, "version": "2026.04.10"},
        ),
    ):
        res_nav = scheduler.trigger_job("nav_daily_extend")
        assert "refresh" in res_nav
        assert res_nav["refresh"]["updated"] == 2
        assert "backfill" in res_nav
        assert res_nav["backfill"]["points"] == 10

        res_isin = scheduler.trigger_job("isin_catalog_update")
        assert res_isin["updated"] is True

        with pytest.raises(ValueError, match="Unknown job ID"):
            scheduler.trigger_job("non_existent_job")


def test_cli_scheduler_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "--help"])
    assert result.exit_code == 0
    assert "Manage background schedulers and automated maintenance jobs." in result.output
    assert "run" in result.output


def test_cli_scheduler_run_with_catchup():
    runner = CliRunner()
    with (
        patch.object(FoliomanScheduler, "trigger_job") as mock_trigger,
        patch.object(FoliomanScheduler, "start") as mock_start,
    ):
        result = runner.invoke(cli, ["scheduler", "run", "--catchup"])
        assert result.exit_code == 0
        assert "Initializing Folioman maintenance scheduler..." in result.output
        assert "Running initial catch-up pass..." in result.output
        mock_trigger.assert_called_once_with("nav_daily_extend")
        mock_start.assert_called_once_with(blocking=True)
