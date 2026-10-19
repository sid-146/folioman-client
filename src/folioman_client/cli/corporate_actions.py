"""CLI subcommands for managing and applying corporate actions."""

from __future__ import annotations

import asyncio

import click

from folioman_client.services.corporate_action_service import CorporateActionService


@click.group(name="corporate-actions")
def corporate_actions_group() -> None:
    """Fetch, inspect, and apply corporate action events (bonuses, splits)."""


@corporate_actions_group.command(name="refresh")
@click.option(
    "--security-id",
    "-s",
    type=int,
    help="Optional specific Security ID to refresh actions for.",
)
@click.option(
    "--since-year",
    "-y",
    type=int,
    default=2016,
    show_default=True,
    help="Earliest year to fetch exchange announcements back to.",
)
@click.pass_context
def refresh_cmd(ctx: click.Context, security_id: int | None, since_year: int) -> None:
    """Fetch corporate action history for held equities from NSE/BSE feeds."""
    service = CorporateActionService()
    click.echo(f"Refreshing corporate actions from exchanges since {since_year}...")
    sec_ids = [security_id] if security_id is not None else None
    summary = asyncio.run(
        service.refresh_corporate_actions(security_ids=sec_ids, since_year=since_year)
    )

    click.echo("-" * 40)
    click.echo(f"Securities Checked: {summary['securities_checked']}")
    click.echo(f"Actions Fetched:    {summary['actions_fetched']}")
    click.echo(f"Errors / Throttle:  {summary['errors']}")
    click.echo("-" * 40)


@corporate_actions_group.command(name="list")
@click.option("--security-id", "-s", type=int, help="Filter by Security ID.")
@click.option("--isin", help="Filter by ISIN.")
@click.option("--symbol", help="Filter by trading symbol.")
@click.option(
    "--kind",
    type=click.Choice(["bonus", "split", "dividend", "rights"], case_sensitive=False),
    help="Filter by corporate action type.",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    security_id: int | None,
    isin: str | None,
    symbol: str | None,
    kind: str | None,
) -> None:
    """List cached corporate action announcements."""
    service = CorporateActionService()
    rows = asyncio.run(
        service.list_references(
            security_id=security_id, isin=isin, symbol=symbol, kind=kind
        )
    )

    if not rows:
        click.echo("No corporate actions found matching filter criteria.")
        return

    click.echo("=" * 80)
    hdr = f"{'ID':<6} {'Ex-Date':<11} {'Type':<10} {'Multiplier':<12} {'Symbol':<12} {'Subject':<35}"
    click.echo(hdr)
    click.echo("-" * 80)
    for r in rows:
        rid = str(r["id"])
        ex_d = r["ex_date"]
        k = r["type"]
        mult = r["unit_multiplier"] or "-"
        sym = r["symbol"] or "-"
        subj = r["subject"][:34]
        click.echo(f"{rid:<6} {ex_d:<11} {k:<10} {mult:<12} {sym:<12} {subj:<35}")
    click.echo("=" * 80)


@corporate_actions_group.command(name="apply")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--folio-id", "-f", type=int, required=True, help="Folio ID.")
@click.option(
    "--reference-id",
    "-r",
    type=int,
    required=True,
    help="CorporateActionReference ID to apply.",
)
@click.pass_context
def apply_cmd(
    ctx: click.Context,
    investor_id: int,
    folio_id: int,
    reference_id: int,
) -> None:
    """Apply a cached bonus or split to an investor folio."""
    service = CorporateActionService()
    click.echo(
        f"Applying corporate action {reference_id} to investor {investor_id}, folio {folio_id}..."
    )
    result = asyncio.run(
        service.apply_corporate_action(investor_id, folio_id, reference_id)
    )
    if result.get("applied"):
        click.echo(
            f"Successfully applied {result['kind']} (multiplier={result['unit_multiplier']}, ex_date={result['ex_date']})."
        )
    else:
        click.echo(f"Action not applied: {result.get('reason')}")
