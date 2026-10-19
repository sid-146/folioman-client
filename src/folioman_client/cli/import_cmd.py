"""CLI subcommands for importing CAS and eCAS statement PDFs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from folioman_client.config import settings
from folioman_client.services.import_service import CASImportService


@click.group(name="import")
def import_group() -> None:
    """Import investment statements (CAS PDFs, demat eCAS)."""


@import_group.command(name="cas")
@click.argument(
    "pdf_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--password",
    "-p",
    prompt=True,
    hide_input=True,
    confirmation_prompt=False,
    help="Password for decrypting the CAS PDF statement.",
)
@click.option(
    "--user-id",
    "-u",
    default=None,
    help="Optional user/advisor account identifier (defaults to configured user_id).",
)
@click.option(
    "--investor-id",
    "-i",
    type=int,
    default=None,
    help="Optional existing investor ID to assign the statement to.",
)
@click.pass_context
def import_cas_cmd(
    ctx: click.Context,
    pdf_path: Path,
    password: str,
    user_id: str | None,
    investor_id: int | None,
) -> None:
    """Import and reconcile a CAMS/KFintech MF CAS or NSDL/CDSL eCAS PDF."""
    active_user_id = user_id or settings.user_id
    service = CASImportService()

    click.echo(f"Processing CAS file '{pdf_path.name}'...")
    try:
        res = asyncio.run(
            service.import_cas(
                pdf_path,
                password,
                user_id=active_user_id,
                investor_id=investor_id,
            )
        )
    except Exception as exc:
        click.secho(f"Import failed: {exc}", fg="red")
        raise click.Abort() from exc

    status_color = "green" if res["status"] == "completed" else "yellow"
    click.echo("=" * 55)
    click.secho(
        f"CAS Import Status: {res['status'].upper()}", fg=status_color, bold=True
    )
    click.echo("=" * 55)
    click.echo(f"Investor Name:          {res.get('investor_name', 'Unknown')}")
    click.echo(f"Masked PAN:             {res.get('pan_masked', 'Not provided')}")
    click.echo(
        f"Statement Type:         {'NSDL/CDSL eCAS' if res.get('is_ecas') else 'Mutual Fund CAS (CAMS/KFin)'}"
    )
    click.echo(f"Schemes Processed:      {res['schemes']:,}")
    click.echo(f"Transactions Created:   {res['transactions_created']:,}")
    click.echo(
        f"Transactions Skipped:   {res['transactions_skipped']:,} (deduplicated)"
    )
    if res["partial_transactions"]:
        click.echo(
            f"Partial Transactions:   {res['partial_transactions']:,} (display-only, pending prior history)"
        )
    if res["holdings_snapshotted"]:
        click.echo(f"Holdings Snapshotted:   {res['holdings_snapshotted']:,}")

    if res["quarantined"]:
        click.secho(f"Quarantined Items:      {len(res['quarantined']):,}", fg="yellow")
        for q in res["quarantined"]:
            click.echo(
                f"  - [{q.get('isin') or 'NO_ISIN'}] {q.get('security')}: {q.get('reason')}"
            )

    if res["incomplete_history"]:
        click.secho(
            f"Incomplete History:     {len(res['incomplete_history']):,} scheme(s) have non-zero opening balance",
            fg="yellow",
        )
        for inc in res["incomplete_history"]:
            click.echo(f"  - Folio {inc['folio']}: {inc['security']} ({inc['reason']})")

    click.echo("=" * 55)
