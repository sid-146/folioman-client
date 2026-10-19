"""CLI subcommands for valuation jobs, historical series, and status."""

from __future__ import annotations

import asyncio
from datetime import date

import click

from folioman_client.errors import FoliomanError
from folioman_client.services.valuation_service import ValuationService


@click.group(name="valuations")
def valuations_group() -> None:
    """Manage daily valuation series, status checks, and recompute ticks."""


@valuations_group.command(name="status")
@click.option("--investor-id", "-i", type=int, default=None, help="Investor ID.")
@click.option("--family-id", "-f", type=int, default=None, help="Family ID.")
@click.pass_context
def status_cmd(
    ctx: click.Context, investor_id: int | None, family_id: int | None
) -> None:
    """Check valuation calculation status and coverage."""
    if investor_id is None and family_id is None:
        raise click.UsageError("Must provide either --investor-id or --family-id")

    service = ValuationService()
    try:
        if investor_id is not None:
            st = asyncio.run(service.get_valuation_status(investor_id))
            click.echo("-" * 40)
            click.echo(f"Investor ID:      {st['investor_id']}")
            click.echo(f"Status:           {st['status'].upper()}")
            click.echo(f"Computed Through: {st['computed_through'] or 'None'}")
            click.echo(f"Recompute From:   {st['recompute_from'] or 'None'}")
            click.echo(f"Is Provisional:   {st['is_provisional']}")
            click.echo("-" * 40)
        elif family_id is not None:
            st = asyncio.run(service.get_family_valuation_status(family_id))
            click.echo("-" * 40)
            click.echo(f"Family ID:        {st['family_id']}")
            click.echo(f"Status:           {st['status'].upper()}")
            click.echo(f"Computed Through: {st['computed_through'] or 'None'}")
            click.echo(f"Is Provisional:   {st['is_provisional']}")
            click.echo("-" * 40)
    except (FoliomanError, ValueError) as exc:
        raise click.ClickException(str(exc))


@valuations_group.command(name="series")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option(
    "--from", "from_date", type=str, default=None, help="Start date (YYYY-MM-DD)."
)
@click.option("--to", "to_date", type=str, default=None, help="End date (YYYY-MM-DD).")
@click.option(
    "--granularity",
    "-g",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default="monthly",
    help="Series sampling frequency.",
)
@click.pass_context
def series_cmd(
    ctx: click.Context,
    investor_id: int,
    from_date: str | None,
    to_date: str | None,
    granularity: str,
) -> None:
    """Print reconstructed historical net-worth time series."""
    try:
        f_date = date.fromisoformat(from_date) if from_date else None
        t_date = date.fromisoformat(to_date) if to_date else None

        service = ValuationService()
        series = asyncio.run(
            service.value_series(
                investor_id, from_date=f_date, to_date=t_date, granularity=granularity
            )
        )
    except (FoliomanError, ValueError) as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"\nNet-Worth Series for Investor {investor_id} ({granularity.title()}):"
    )
    click.echo(
        f"{'Date':<12} {'Valuation (INR)':>18} {'Cost Basis (INR)':>18} {'Stale':>8}"
    )
    click.echo("-" * 60)
    for pt in series["points"]:
        stale_flag = "YES" if pt.get("stale") else "no"
        click.echo(
            f"{pt['date']!s:<12} {pt['value_inr']:>18,.2f} {pt['invested_inr']:>18,.2f} {stale_flag:>8}"
        )
    click.echo(f"Total Points: {len(series['points'])}\n")


@valuations_group.command(name="tick")
@click.option("--pending", is_flag=True, help="Process pending valuations only.")
@click.option("--extend", is_flag=True, help="Enqueue daily extension only.")
@click.pass_context
def tick_cmd(ctx: click.Context, pending: bool, extend: bool) -> None:
    """Trigger background valuation ticks for pending or daily extension jobs."""
    service = ValuationService()

    try:
        if extend:
            click.echo("Enqueuing daily extension for all investors...")
            cnt = asyncio.run(service.enqueue_daily_extend())
            click.echo(f"Queued {cnt} investors for daily extension.")
        elif pending:
            click.echo("Processing pending valuations...")
            cnt = asyncio.run(service.process_pending_valuations())
            click.echo(f"Processed {cnt} pending valuations.")
        else:
            click.echo("Running valuation catch-up and pending ticks...")
            catch_cnt = asyncio.run(service.enqueue_catch_up_if_stale())
            proc_cnt = asyncio.run(service.process_pending_valuations())
            click.echo(f"Catch-up queued: {catch_cnt}, Processed: {proc_cnt}")
    except (FoliomanError, ValueError) as exc:
        raise click.ClickException(str(exc))
