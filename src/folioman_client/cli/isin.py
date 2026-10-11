"""CLI subcommands for managing the ISIN and scheme reference catalog."""

from __future__ import annotations

import asyncio
from pathlib import Path
import click

from folioman_client.services.isin_service import ISINService


@click.group(name="isin")
def isin_group() -> None:
    """Manage the local scheme and ISIN reference database."""


@isin_group.command(name="status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Display the current population status of the reference catalog."""
    service = ISINService()
    status = asyncio.run(service.get_reference_status())

    click.echo("=" * 45)
    click.echo("Folioman Reference Master Catalog Status")
    click.echo("=" * 45)
    click.echo(f"Seeded:                 {'Yes' if status['is_seeded'] else 'No'}")
    click.echo(f"Catalog Version:        {status['version'] or 'Not initialized'}")
    click.echo(f"Mutual Fund Schemes:    {status['schemes_count']:,}")
    click.echo(f"National Securities/ISIN:{status['isins_count']:,}")
    click.echo(f"2018-01-31 Grandf. NAVs:{status['grandfathering_count']:,}")
    click.echo("=" * 45)


@isin_group.command(name="seed")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force re-seed by purging existing reference data.",
)
@click.option(
    "--source",
    "-s",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Optional path to a custom casparser-isin SQLite database file.",
)
@click.pass_context
def seed_cmd(ctx: click.Context, force: bool, source: Path | None) -> None:
    """Ingest reference master catalog into the active database."""
    service = ISINService()
    click.echo("Seeding reference data into active database...")
    result = asyncio.run(service.seed_reference_data(force=force, source_path=source))

    if not result.get("seeded", False) and not force:
        click.echo(
            f"Reference database already populated ({result['schemes_count']:,} schemes, "
            f"{result['isins_count']:,} ISINs, v{result['version']}). Use --force to overwrite."
        )
    else:
        click.secho(
            f"Successfully seeded reference database v{result['version']}:\n"
            f"  - Schemes: {result['schemes_count']:,}\n"
            f"  - Securities / ISINs: {result['isins_count']:,}\n"
            f"  - 31-Jan-2018 NAVs: {result['grandfathering_count']:,}",
            fg="green",
        )


@isin_group.command(name="resolve")
@click.argument("isin")
@click.pass_context
def resolve_cmd(ctx: click.Context, isin: str) -> None:
    """Resolve an ISIN to its full scheme and security metadata."""
    service = ISINService()
    result = asyncio.run(service.resolve_isin(isin))

    if not result:
        click.secho(f"No security or scheme found for ISIN '{isin}'.", fg="red")
        return

    click.echo("=" * 50)
    click.echo(f"ISIN:               {result['isin']}")
    click.echo(f"Name:               {result['name']}")
    click.echo(f"Type:               {result['security_type']}")
    if result["symbol"]:
        click.echo(f"Symbol:             {result['symbol']} ({result['exchange']})")
    if result["amfi_code"]:
        click.echo(f"AMFI Code:          {result['amfi_code']}")
    if result["rta"]:
        click.echo(f"RTA:                {result['rta']} (Code: {result['rta_code']})")
    if result["sebi_category"]:
        click.echo(f"SEBI Category:      {result['sebi_category']}")
    if result["grandfathering_nav"] is not None:
        click.echo(f"31-Jan-2018 NAV:    INR {result['grandfathering_nav']}")
    click.echo("=" * 50)


@isin_group.command(name="search")
@click.argument("query")
@click.option(
    "--limit",
    "-l",
    type=int,
    default=10,
    help="Maximum number of search results to display.",
)
@click.pass_context
def search_cmd(ctx: click.Context, query: str, limit: int) -> None:
    """Search mutual fund schemes by text name, AMFI code, or ISIN."""
    service = ISINService()
    results = asyncio.run(service.search_schemes(query, limit=limit))

    if not results:
        click.echo(f"No schemes matched '{query}'.")
        return

    click.echo(f"Found {len(results)} match(es) for '{query}':")
    click.echo("-" * 75)
    for s in results:
        click.echo(
            f"[{s['amfi_code'] or '------'}] {s['isin'] or '------------'} | {s['name']} ({s['rta']})"
        )
    click.echo("-" * 75)


@isin_group.command(name="update")
@click.pass_context
def update_cmd(ctx: click.Context) -> None:
    """Check upstream for newer casparser-isin data and update active database."""
    service = ISINService()
    click.echo("Checking upstream repository for newer reference data...")
    res = asyncio.run(service.update_reference_data())
    if res.get("updated"):
        click.secho(res["message"], fg="green")
    else:
        click.echo(res["message"])
