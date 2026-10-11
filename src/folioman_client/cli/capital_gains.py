"""CLI subcommands for realized capital gains and Schedule 112A tax reports."""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path
import click

from folioman_client.services.capital_gains_service import CapitalGainsService


@click.group(name="capital-gains")
def capital_gains_group() -> None:
    """Compute and report realized capital gains (STCG/LTCG) and Schedule 112A."""


@capital_gains_group.command(name="list")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option(
    "--include-unreconciled",
    is_flag=True,
    help="Include transactions from unreconciled folios.",
)
@click.pass_context
def list_cmd(ctx: click.Context, investor_id: int, include_unreconciled: bool) -> None:
    """List realized STCG and LTCG across every financial year."""
    service = CapitalGainsService()
    fys = asyncio.run(
        service.list_capital_gains_by_fy(investor_id, include_unreconciled=include_unreconciled)
    )

    if not fys:
        click.echo(f"No realized capital gains recorded for investor {investor_id}.")
        return

    click.echo(f"\nRealized Capital Gains by Financial Year for Investor {investor_id}:")
    click.echo(f"{'FY':<10} {'STCG (INR)':>16} {'LTCG (INR)':>16} {'Net Total (INR)':>18}")
    click.echo("-" * 64)
    for pt in fys:
        net = pt["stcg"] + pt["ltcg"]
        click.echo(
            f"{pt['fy']:<10} {pt['stcg']:>16,.2f} {pt['ltcg']:>16,.2f} {net:>18,.2f}"
        )
    click.echo("")


@capital_gains_group.command(name="report")
@click.option("--investor-id", "-i", type=int, required=True, help="Investor ID.")
@click.option("--fy", type=str, required=True, help="Financial year (e.g. '2024-25').")
@click.option(
    "--include-unreconciled",
    is_flag=True,
    help="Include transactions from unreconciled folios.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Export Schedule 112A report to CSV file.",
)
@click.pass_context
def report_cmd(
    ctx: click.Context,
    investor_id: int,
    fy: str,
    include_unreconciled: bool,
    csv_path: str | None,
) -> None:
    """Generate lot-level capital gains report with Section 112A grandfathering."""
    service = CapitalGainsService()
    report = asyncio.run(
        service.get_capital_gains_report(
            investor_id, fy, include_unreconciled=include_unreconciled
        )
    )

    click.echo("=" * 78)
    click.echo(f"Capital Gains Report: Investor {investor_id} (FY {fy})")
    click.echo(f"Total STCG:    INR {report['stcg_total']:,.2f}")
    click.echo(f"Total LTCG:    INR {report['ltcg_total']:,.2f}")
    if report.get("exempt_total"):
        click.echo(f"Total Exempt:  INR {report['exempt_total']:,.2f}")
    click.echo(f"Disposal Lots: {len(report['rows'])}")
    click.echo("=" * 78)

    if report["rows"]:
        click.echo(
            f"\n{'Security':<24} {'Units':>8} {'Term':>6} {'Acquired':<11} {'Sold':<11} {'Sale (INR)':>12} {'Cost (INR)':>12} {'Gain (INR)':>12}"
        )
        click.echo("-" * 105)
        for r in report["rows"]:
            gf_flag = " (!)" if r["grandfathering_unavailable"] else ""
            click.echo(
                f"{r['name'][:22]:<24} {r['units']:>8.3f} {r['term'].upper():>6} "
                f"{str(r['acquired_on']):<11} {str(r['sold_on']):<11} "
                f"{r['sale_value']:>12,.2f} {r['cost']:>12,.2f} {r['gain']:>12,.2f}{gf_flag}"
            )
        click.echo("")

    if csv_path:
        click.echo(f"Exporting official Schedule 112A CSV to {csv_path}...")
        s112a = asyncio.run(
            service.get_schedule_112a(
                investor_id, fy, include_unreconciled=include_unreconciled
            )
        )
        out_p = Path(csv_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=s112a["columns"])
            writer.writeheader()
            for r in s112a["rows"]:
                writer.writerow(r)
        click.echo(f"Successfully exported {s112a['row_count']} rows to {csv_path}.")
