"""CLI subcommands for ledger and holding reconciliation."""

from __future__ import annotations

import asyncio

import click

from folioman_client.services.reconciliation_service import ReconciliationService


@click.group(name="reconcile")
def reconcile_group() -> None:
    """Reconcile trade ledgers against reported statement holdings."""


@reconcile_group.command(name="all")
@click.option(
    "--investor-id",
    "-i",
    type=int,
    help="Optional investor ID to reconcile. If omitted, reconciles all investors.",
)
@click.pass_context
def reconcile_all_cmd(ctx: click.Context, investor_id: int | None) -> None:
    """Run reconciliation across positions, updating integrity metrics and tax safety."""
    service = ReconciliationService()

    if investor_id is not None:
        click.echo(f"Reconciling positions for investor {investor_id}...")
        summary = asyncio.run(service.reconcile_investor(investor_id))
        click.echo("-" * 40)
        click.echo(f"Investor ID:           {summary['investor_id']}")
        click.echo(f"Securities Reconciled: {summary['securities_reconciled']}")
        click.echo(f"Folio Positions:       {summary['statuses_count']}")
        click.echo(f"Tax-Safe Positions:    {summary['tax_safe_count']}")
        click.echo(f"Mismatches:            {summary['mismatch_count']}")
        click.echo("-" * 40)
    else:
        click.echo("Reconciling positions across all investors...")
        summary = asyncio.run(service.reconcile_all())
        click.echo("-" * 40)
        click.echo(f"Investors:          {summary['investors_count']}")
        click.echo(f"Folio Positions:    {summary['statuses_count']}")
        click.echo(f"Tax-Safe Positions: {summary['tax_safe_count']}")
        click.echo(f"Mismatches:         {summary['mismatch_count']}")
        click.echo("-" * 40)


@reconcile_group.command(name="acknowledge")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--security-id", "-s", type=int, required=True, help="Security ID.")
@click.option("--folio-id", "-f", type=int, required=True, help="Folio ID.")
@click.pass_context
def acknowledge_cmd(
    ctx: click.Context, investor_id: int, security_id: int, folio_id: int
) -> None:
    """Acknowledge a unit mismatch for a specific position."""
    service = ReconciliationService()
    click.echo(
        f"Acknowledging mismatch for investor {investor_id}, security {security_id}, folio {folio_id}..."
    )
    result = asyncio.run(
        service.acknowledge_mismatch(investor_id, security_id, folio_id)
    )
    click.echo(f"Updated Status: {result['status']} (tax_safe={result['tax_safe']})")


@reconcile_group.command(name="clear")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--security-id", "-s", type=int, required=True, help="Security ID.")
@click.option("--folio-id", "-f", type=int, required=True, help="Folio ID.")
@click.pass_context
def clear_cmd(
    ctx: click.Context, investor_id: int, security_id: int, folio_id: int
) -> None:
    """Clear user acknowledgement, restoring real integrity status."""
    service = ReconciliationService()
    click.echo(
        f"Clearing acknowledgement for investor {investor_id}, security {security_id}, folio {folio_id}..."
    )
    result = asyncio.run(
        service.clear_acknowledgement(investor_id, security_id, folio_id)
    )
    click.echo(f"Restored Status: {result['status']} (tax_safe={result['tax_safe']})")
