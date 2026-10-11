"""Tests for Folioman ISIN CLI commands."""

from __future__ import annotations

from pathlib import Path
from click.testing import CliRunner

from folioman_client.cli.main import cli
from folioman_client.config import settings


def test_cli_isin_lifecycle(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    db_file = tmp_path / "cli_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(settings, "database_url", db_url)

    # 1. Initial status before seeding
    res_status = runner.invoke(cli, ["--database-url", db_url, "isin", "status"])
    assert res_status.exit_code == 0
    assert "Seeded:                 No" in res_status.output

    # 2. Seed the reference database
    res_seed = runner.invoke(cli, ["--database-url", db_url, "isin", "seed"])
    assert res_seed.exit_code == 0
    assert "Successfully seeded reference database" in res_seed.output

    # 3. Status after seeding
    res_status_after = runner.invoke(cli, ["--database-url", db_url, "isin", "status"])
    assert res_status_after.exit_code == 0
    assert "Seeded:                 Yes" in res_status_after.output

    # 4. Resolve a mutual fund ISIN
    res_resolve = runner.invoke(cli, ["--database-url", db_url, "isin", "resolve", "INF179K01319"])
    assert res_resolve.exit_code == 0
    assert "INF179K01319" in res_resolve.output
    assert "HDFC" in res_resolve.output

    # 5. Resolve nonexistent ISIN
    res_resolve_none = runner.invoke(cli, ["--database-url", db_url, "isin", "resolve", "IN9999999999"])
    assert res_resolve_none.exit_code == 0
    assert "No security or scheme found" in res_resolve_none.output

    # 6. Search schemes
    res_search = runner.invoke(cli, ["--database-url", db_url, "isin", "search", "Arbitrage", "--limit", "3"])
    assert res_search.exit_code == 0
    assert "match(es)" in res_search.output

    # 7. Update check
    res_update = runner.invoke(cli, ["--database-url", db_url, "isin", "update"])
    assert res_update.exit_code == 0
