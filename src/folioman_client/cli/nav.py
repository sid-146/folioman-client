"""CLI subcommands for managing market NAVs and closing prices."""

from __future__ import annotations

import asyncio
import click

from folioman_client.services.nav_service import NAVService


@click.group(name="navs")
def nav_group() -> None:
    """Manage mutual fund NAVs and market closing prices."""


@nav_group.command(name="refresh")
@click.option(
    "--types",
    "-t",
    help="Comma-separated asset types to refresh (e.g. mf,equity,crypto). Defaults to all.",
)
@click.pass_context
def refresh_cmd(ctx: click.Context, types: str | None) -> None:
    """Fetch the latest available prices for held securities."""
    type_list = [t.strip() for t in types.split(",")] if types else None
    service = NAVService()
    click.echo("Refreshing latest NAVs and market prices...")
    summary = asyncio.run(service.refresh_navs(types=type_list))

    click.echo("-" * 40)
    click.echo(f"Updated: {summary['updated']}")
    click.echo(f"Skipped: {summary['skipped']}")
    click.echo(f"Errors:  {summary['errors']}")
    click.echo("-" * 40)


@nav_group.command(name="backfill")
@click.option(
    "--security-id",
    "-s",
    type=int,
    help="Optional specific Security ID to backfill.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force re-fetching the full historical price series.",
)
@click.pass_context
def backfill_cmd(ctx: click.Context, security_id: int | None, force: bool) -> None:
    """Backfill historical prices for securities."""
    service = NAVService()
    click.echo(
        f"Backfilling NAV history ({'forced full scan' if force else 'extending tails and gaps'})..."
    )
    summary = asyncio.run(service.backfill_navs(security_id=security_id, force=force))

    click.echo("-" * 40)
    click.echo(f"Securities Updated: {summary['securities']}")
    click.echo(f"Data Points Added:  {summary['points']}")
    click.echo(f"Skipped:           {summary['skipped']}")
    click.echo(f"Closed / Inactive: {summary['closed']}")
    click.echo(f"Errors:            {summary['errors']}")
    click.echo("-" * 40)


@nav_group.command(name="status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Display NAV freshness and tracking status for held securities."""
    service = NAVService()
    freshness = asyncio.run(service.get_nav_freshness())

    click.echo("=" * 80)
    click.echo("Folioman NAV Freshness & Price Feed Status")
    click.echo("=" * 80)
    click.echo(f"As-Of Trading Day:     {freshness['as_of']}")
    click.echo(f"Last Price Written At: {freshness['last_refreshed_at'] or 'Never'}")
    click.echo(f"Next Scheduled Run:    {freshness['next_refresh_at']}")
    click.echo("-" * 80)

    securities = freshness.get("securities", [])
    if not securities:
        click.echo("No active securities found in portfolio.")
        click.echo("=" * 80)
        return

    # Table format
    hdr = f"{'ID':<4} {'Type':<8} {'Status':<8} {'Lag':<5} {'Latest Date':<12} {'Points':<8} {'Name':<30}"
    click.echo(hdr)
    click.echo("-" * 80)

    for sec in securities:
        sec_id = str(sec["security_id"])
        stype = sec["security_type"]
        status = sec["status"]
        lag = (
            f"{sec['lag_trading_days']}d"
            if sec["lag_trading_days"] is not None
            else "-"
        )
        latest = str(sec["latest_nav_date"] or "None")
        pts = str(sec["points"])
        name = sec["name"][:29]
        click.echo(
            f"{sec_id:<4} {stype:<8} {status:<8} {lag:<5} {latest:<12} {pts:<8} {name:<30}"
        )

    click.echo("=" * 80)
