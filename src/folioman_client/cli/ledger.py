"""CLI subcommands for managing investors, folios, and transactions."""

from __future__ import annotations

import asyncio
import click

from folioman_client.errors import DuplicateInvestorError, FoliomanDatabaseError
from folioman_client.services.ledger_service import LedgerService


@click.group(name="investors")
def investors_group() -> None:
    """Manage investor profiles."""


@investors_group.command(name="list")
@click.option("--family-id", type=int, help="Filter by family group ID.")
@click.option("--unaffiliated", is_flag=True, help="List only unaffiliated investors.")
@click.pass_context
def list_investors_cmd(
    ctx: click.Context, family_id: int | None, unaffiliated: bool
) -> None:
    """List all registered investors."""
    service = LedgerService()
    investors = asyncio.run(
        service.list_investors(family_id=family_id, unaffiliated=unaffiliated)
    )

    if not investors:
        click.echo("No investors found.")
        return

    click.echo("=" * 80)
    hdr = f"{'ID':<6} {'Name':<30} {'PAN':<12} {'Email':<25}"
    click.echo(hdr)
    click.echo("-" * 80)
    for inv in investors:
        iid = str(inv["id"])
        name = inv["name"][:29]
        pan = inv["pan_masked"] or "-"
        email = inv["email"][:24] if inv["email"] else "-"
        click.echo(f"{iid:<6} {name:<30} {pan:<12} {email:<25}")
    click.echo("=" * 80)


@investors_group.command(name="create")
@click.option("--name", "-n", required=True, help="Full name of investor.")
@click.option("--pan", "-p", help="Permanent Account Number (PAN).")
@click.option("--email", "-e", default="", help="Email address.")
@click.option("--is-huf", is_flag=True, help="Mark as Hindu Undivided Family (HUF).")
@click.pass_context
def create_investor_cmd(
    ctx: click.Context, name: str, pan: str | None, email: str, is_huf: bool
) -> None:
    """Create a new investor with encrypted PAN storage."""
    service = LedgerService()
    try:
        inv = asyncio.run(
            service.create_investor(name=name, pan=pan, email=email, is_huf=is_huf)
        )
    except (DuplicateInvestorError, FoliomanDatabaseError) as exc:
        raise click.ClickException(str(exc))

    click.echo(
        f"Created investor {inv['name']} (ID: {inv['id']}, PAN: {inv['pan_masked'] or 'None'})."
    )


@click.group(name="folios")
def folios_group() -> None:
    """Manage mutual fund folios and demat accounts."""


@folios_group.command(name="list")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.pass_context
def list_folios_cmd(ctx: click.Context, investor_id: int) -> None:
    """List folios and demat accounts for an investor."""
    service = LedgerService()
    folios = asyncio.run(service.list_folios(investor_id))

    if not folios:
        click.echo(f"No folios found for investor {investor_id}.")
        return

    click.echo("=" * 80)
    hdr = f"{'ID':<6} {'Number':<25} {'AMC/DP':<15} {'Type':<10} {'Broker':<15}"
    click.echo(hdr)
    click.echo("-" * 80)
    for f in folios:
        fid = str(f["id"])
        num = f["number"][:24]
        amc = f["amc_code"][:14] if f["amc_code"] else "-"
        ftype = f["folio_type"]
        broker = f["broker"][:14] if f["broker"] else "-"
        click.echo(f"{fid:<6} {num:<25} {amc:<15} {ftype:<10} {broker:<15}")
    click.echo("=" * 80)


@folios_group.command(name="merge")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option(
    "--source-id", "-s", type=int, required=True, help="Source Folio ID to merge from."
)
@click.option(
    "--target-id", "-t", type=int, required=True, help="Target Folio ID to merge into."
)
@click.pass_context
def merge_folios_cmd(
    ctx: click.Context, investor_id: int, source_id: int, target_id: int
) -> None:
    """Merge source folio into target folio, moving all transactions and holdings."""
    service = LedgerService()
    click.echo(
        f"Merging folio {source_id} -> {target_id} for investor {investor_id}..."
    )
    res = asyncio.run(service.merge_folios(investor_id, source_id, target_id))
    click.echo(
        f"Merge complete: {res['transactions_moved']} transactions and {res['holdings_moved']} holdings moved."
    )


@click.group(name="transactions")
def transactions_group() -> None:
    """Inspect and manage trade transactions in the immutable ledger."""


@transactions_group.command(name="list")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--security-id", "-s", type=int, help="Filter by Security ID.")
@click.option("--folio-id", "-f", type=int, help="Filter by Folio ID.")
@click.pass_context
def list_transactions_cmd(
    ctx: click.Context,
    investor_id: int,
    security_id: int | None,
    folio_id: int | None,
) -> None:
    """List transactions for an investor ordered chronologically."""
    service = LedgerService()
    txns = asyncio.run(
        service.list_transactions(
            investor_id, security_id=security_id, folio_id=folio_id
        )
    )

    if not txns:
        click.echo(f"No transactions found for investor {investor_id}.")
        return

    click.echo("=" * 90)
    hdr = f"{'ID':<6} {'Date':<11} {'Type':<8} {'Units':<12} {'NAV/Price':<12} {'Amount':<14} {'Security':<25}"
    click.echo(hdr)
    click.echo("-" * 90)
    for t in txns:
        tid = str(t["id"])
        dt = t["date"]
        ttype = t["type"]
        units = t["units"]
        nav = t["nav"]
        amt = t["amount"] or "-"
        sec = t["security_name"][:24]
        click.echo(
            f"{tid:<6} {dt:<11} {ttype:<8} {units:<12} {nav:<12} {amt:<14} {sec:<25}"
        )
    click.echo("=" * 90)


@click.group(name="holdings")
def holdings_group() -> None:
    """Inspect active portfolio holdings."""


@holdings_group.command(name="list")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.pass_context
def list_holdings_cmd(ctx: click.Context, investor_id: int) -> None:
    """List active positions (from ledger or statement snapshots)."""
    service = LedgerService()
    holdings = asyncio.run(service.list_holdings(investor_id))

    if not holdings:
        click.echo(f"No active holdings found for investor {investor_id}.")
        return

    click.echo("=" * 80)
    hdr = f"{'ID':<6} {'Type':<8} {'Units':<14} {'Symbol/ISIN':<15} {'Name':<33}"
    click.echo(hdr)
    click.echo("-" * 80)
    for h in holdings:
        hid = str(h["security_id"])
        stype = h["type"]
        units = h["units"]
        sym = h["symbol"] or h["isin"]
        name = h["name"][:32]
        click.echo(f"{hid:<6} {stype:<8} {units:<14} {sym:<15} {name:<33}")
    click.echo("=" * 80)
