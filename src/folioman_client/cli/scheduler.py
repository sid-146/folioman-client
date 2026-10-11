"""CLI subcommands for managing background tasks and the scheduler."""

from __future__ import annotations

import click

from folioman_client.services.scheduler import FoliomanScheduler


@click.group(name="scheduler")
def scheduler_group() -> None:
    """Manage background schedulers and automated maintenance jobs."""


@scheduler_group.command(name="run")
@click.option(
    "--catchup",
    "-c",
    is_flag=True,
    help="Trigger an immediate catch-up pass on startup before entering the schedule.",
)
@click.pass_context
def run_cmd(ctx: click.Context, catchup: bool) -> None:
    """Run the scheduler as a blocking foreground daemon process."""
    click.echo("Initializing Folioman maintenance scheduler...")
    scheduler = FoliomanScheduler()
    if catchup:
        click.echo("Running initial catch-up pass...")
        scheduler.trigger_job("nav_daily_extend")

    click.echo("Scheduler running (Ctrl+C to stop)...")
    try:
        scheduler.start(blocking=True)
    except (KeyboardInterrupt, SystemExit):
        click.echo("\nStopping scheduler...")
        scheduler.shutdown()
        click.echo("Scheduler stopped.")
