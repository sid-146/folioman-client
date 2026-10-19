"""Main Click CLI entry point for folioman command line interface."""

from __future__ import annotations

import asyncio
import sys
import warnings
from typing import Any

import click

from folioman_client import __version__
from folioman_client.cli.capital_gains import capital_gains_group
from folioman_client.cli.corporate_actions import corporate_actions_group
from folioman_client.cli.import_cmd import import_group
from folioman_client.cli.isin import isin_group
from folioman_client.cli.ledger import (
    folios_group,
    holdings_group,
    investors_group,
    transactions_group,
)
from folioman_client.cli.nav import nav_group
from folioman_client.cli.portfolio import portfolio_group
from folioman_client.cli.reconcile import reconcile_group
from folioman_client.cli.scheduler import scheduler_group
from folioman_client.cli.symbols import symbols_group
from folioman_client.cli.valuations import valuations_group
from folioman_client.config import settings
from folioman_client.errors import FoliomanError


class FoliomanCLI(click.Group):
    """Custom Click Group that catches unhandled domain errors and reports them cleanly."""

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except FoliomanError as exc:
            raise click.ClickException(str(exc)) from None


@click.group(cls=FoliomanCLI)
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

    if sys.platform == "win32":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass


# Register subcommands
cli.add_command(isin_group)
cli.add_command(import_group)
cli.add_command(nav_group)
cli.add_command(scheduler_group)
cli.add_command(reconcile_group)
cli.add_command(symbols_group)
cli.add_command(corporate_actions_group)
cli.add_command(investors_group)
cli.add_command(folios_group)
cli.add_command(transactions_group)
cli.add_command(holdings_group)
cli.add_command(portfolio_group)
cli.add_command(valuations_group)
cli.add_command(capital_gains_group)

if __name__ == "__main__":
    cli()
