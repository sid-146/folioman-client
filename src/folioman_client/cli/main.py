"""Main Click CLI entry point for folioman command line interface."""

from __future__ import annotations

import click

from folioman_client import __version__
from folioman_client.cli.isin import isin_group
from folioman_client.config import settings


@click.group()
@click.version_option(version=__version__, prog_name="folioman")
@click.option(
    "--database-url",
    envvar="FOLIOMAN_DATABASE_URL",
    help="SQLAlchemy database connection URL (e.g. postgresql+psycopg://...)",
)
@click.pass_context
def cli(ctx: click.Context, database_url: str | None) -> None:
    """Folioman — Local-first Portfolio Management & Accounting Engine."""
    ctx.ensure_object(dict)
    if database_url:
        settings.database_url = database_url


# Register subcommands
cli.add_command(isin_group)

if __name__ == "__main__":
    cli()
