"""CLI subcommands for portfolio summary and allocation rollups."""

from __future__ import annotations

import asyncio
from datetime import date

import click

from folioman_client.errors import FoliomanError
from folioman_client.services.valuation_service import ValuationService


@click.group(name="portfolio")
def portfolio_group() -> None:
    """Query portfolio summaries, valuations, and performance metrics."""


@portfolio_group.command(name="summary")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--as-of", type=str, default=None, help="Valuation date (YYYY-MM-DD).")
@click.pass_context
def summary_cmd(ctx: click.Context, investor_id: int, as_of: str | None) -> None:
    """Print overall portfolio summary, metrics, and asset mix for an investor."""
    try:
        as_of_date = date.fromisoformat(as_of) if as_of else None
        service = ValuationService()
        summary = asyncio.run(
            service.build_investor_summary(investor_id, as_of=as_of_date)
        )
    except (FoliomanError, ValueError) as exc:
        raise click.ClickException(f"{type(exc).__name__}: {exc}")

    click.echo("=" * 60)
    click.echo(f"Portfolio Summary for Investor ID: {investor_id}")
    click.echo(f"As of:              {summary['as_of']}")
    click.echo(f"Total Valuation:    INR {summary['total_inr']:,.2f}")
    if summary["day_change_inr"] is not None:
        click.echo(f"Day Change:         INR {summary['day_change_inr']:,.2f}")
    if summary["xirr"] is not None:
        click.echo(f"XIRR:               {summary['xirr'] * 100:.2f}%")
    click.echo(f"Holdings:           {summary['holdings_count']}")
    click.echo(
        f"Tax-Ready Folios:   {summary['tax_ready_count']} of {summary['integrity_unit_count']}"
    )
    click.echo("=" * 60)

    if summary["asset_mix"]:
        click.echo("\nAsset Allocation:")
        for am in summary["asset_mix"]:
            click.echo(
                f"  - {am['security_type'].title():<15} INR {am['value_inr']:,.2f}"
            )

    if summary["top_holdings"]:
        click.echo("\nTop Holdings:")
        for h in summary["top_holdings"]:
            val_str = (
                f"INR {h['value_inr']:,.2f}"
                if h["value_inr"] is not None
                else "Unpriced"
            )
            ret_str = (
                f"({h['return_pct'] * 100:+.1f}%)"
                if h["return_pct"] is not None
                else ""
            )
            click.echo(
                f"  * {h['name'][:30]:<32} {h['units']:>10.3f} units  {val_str:>16} {ret_str}"
            )

    if summary["period_returns"]:
        click.echo("\nPeriod Returns:")
        for pr in summary["period_returns"]:
            ann_str = f"{pr['annualized'] * 100:.2f}% p.a."
            abs_str = (
                f"({pr['absolute'] * 100:+.2f}%)" if pr["absolute"] is not None else ""
            )
            click.echo(f"  - {pr['period']:<6} {ann_str:<15} {abs_str}")
    click.echo("")
