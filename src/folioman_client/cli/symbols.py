"""CLI subcommands for demat equity and bond symbol resolution."""

from __future__ import annotations

import asyncio
import click

from folioman_client.services.equity_symbol_service import EquitySymbolService


@click.group(name="symbols")
def symbols_group() -> None:
    """Resolve and manage exchange trading symbols for demat holdings."""


@symbols_group.command(name="resolve")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Check for symbol matches without updating the database.",
)
@click.option(
    "--backfill",
    is_flag=True,
    help="Automatically trigger historical price backfill for newly resolved symbols.",
)
@click.option(
    "--force-backfill",
    is_flag=True,
    help="Force full price backfill even if some price points already exist.",
)
@click.pass_context
def resolve_cmd(
    ctx: click.Context,
    dry_run: bool,
    backfill: bool,
    force_backfill: bool,
) -> None:
    """Resolve missing NSE/BSE symbols for demat securities using ref_isins catalog."""
    service = EquitySymbolService()
    click.echo(
        f"Resolving trading symbols ({'dry run' if dry_run else 'live update'})..."
    )
    summary = asyncio.run(
        service.resolve_symbols(
            dry_run=dry_run, backfill=backfill, force_backfill=force_backfill
        )
    )

    click.echo("-" * 40)
    click.echo(f"Unresolved Securities: {summary['unresolved_count']}")
    click.echo(f"Symbols Matched:       {summary['matched_count']}")
    click.echo(f"Symbols Updated:       {summary['updated_count']}")
    click.echo(f"Still Unmatched:       {summary['unmatched_count']}")
    click.echo("-" * 40)

    if summary["matched"]:
        click.echo("\nMatched Securities:")
        for m in summary["matched"]:
            click.echo(f"  • {m['isin']} -> {m['symbol']} ({m['exchange']}) - {m['name']}")

    if summary["unmatched"]:
        click.echo("\nUnmatched Securities:")
        for u in summary["unmatched"]:
            click.echo(f"  • {u['isin']} - {u['name']}")

    if summary.get("backfill"):
        bf = summary["backfill"]
        click.echo("\nBackfill Summary:")
        click.echo(f"  Securities: {bf.get('securities', 0)}")
        click.echo(f"  Points:     {bf.get('points', 0)}")
