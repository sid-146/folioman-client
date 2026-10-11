"""Capital Gains Service for Folioman Client.

Calculates realized STCG/LTCG, Section 112A grandfathered capital gains,
and official Schedule 112A tax report rows for Indian financial years.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from folioman_client.core.price_feeds.casparser_fmv import fmv_lookup as _mf_fmv
from folioman_client.core.reconciliation import IntegrityStatus
from folioman_client.core.tax import compute_gain_lines, compute_schedule_112a, get_policy
from folioman_client.core.tax.india import GRANDFATHER_FMV_DATE, india_fy_label, india_fy_range
from folioman_client.core.tax.models import Term
from folioman_client.core.tax.schedule_112a import SCHEDULE_112A_CSV_COLUMNS
from folioman_client.db import create_folioman_engine, create_sessionmaker
from folioman_client.db.models import (
    GrandfatheringNAV,
    Investor,
    NAVHistory,
    Security,
    SecurityIntegrityStatus,
)
from folioman_client.services.projected_ledger import (
    demerger_reductions,
    projected_transactions,
    security_key,
)

_Q2 = Decimal("0.01")


def _folio_tax_ready(status: IntegrityStatus | None, *, include_unreconciled: bool) -> bool:
    """Check if folio is tax ready."""
    if status is None:
        return include_unreconciled
    if status is IntegrityStatus.USER_ACKNOWLEDGED:
        return False
    if include_unreconciled:
        return status is not IntegrityStatus.SNAPSHOT_ONLY
    return status in (IntegrityStatus.FULL_HISTORY, IntegrityStatus.RECONCILED)


class CapitalGainsService:
    """Indian Capital Gains and Schedule 112A computation service."""

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = session_factory or create_sessionmaker(self.engine)

    async def _tax_ready_transactions(
        self, session: AsyncSession, investor_id: int, *, include_unreconciled: bool
    ) -> list[Any]:
        """Fetch core transactions from tax-ready (security, folio) buckets."""
        stmt = (
            select(SecurityIntegrityStatus)
            .options(
                selectinload(SecurityIntegrityStatus.security),
                selectinload(SecurityIntegrityStatus.folio),
            )
            .where(SecurityIntegrityStatus.investor_id == investor_id)
        )
        statuses = (await session.execute(stmt)).scalars().all()
        status_map = {
            (security_key(st.security), st.folio.number if st.folio else ""): IntegrityStatus(st.status)
            for st in statuses
        }

        all_txns = await projected_transactions(session, investor_id)
        return [
            core
            for core in all_txns
            if _folio_tax_ready(
                status_map.get((security_key(core.security), core.folio_number or "")),
                include_unreconciled=include_unreconciled,
            )
        ]

    async def _build_fmv_lookup(
        self, session: AsyncSession, isins: Sequence[str]
    ) -> Callable[[str, date], Decimal | None]:
        """Build synchronous FMV lookup pre-seeded with GrandfatheringNAV and NAVHistory."""
        clean_isins = {i.strip().upper() for i in isins if i}
        fmv_cache: dict[str, Decimal] = {}

        if clean_isins:
            # 1. Query ref_grandfathering_navs table
            stmt_gf = select(GrandfatheringNAV.isin, GrandfatheringNAV.nav).where(
                GrandfatheringNAV.isin.in_(list(clean_isins))
            )
            for isin, nav in (await session.execute(stmt_gf)).all():
                if nav is not None:
                    fmv_cache[isin] = nav

            # 2. Query NAVHistory on/before 2018-01-31 for listed securities missing in gf table
            missing = clean_isins - set(fmv_cache.keys())
            if missing:
                stmt_sec = select(Security.id, Security.isin).where(Security.isin.in_(list(missing)))
                sec_map = dict((await session.execute(stmt_sec)).all())
                if sec_map:
                    stmt_nav = (
                        select(NAVHistory.security_id, NAVHistory.nav)
                        .where(
                            NAVHistory.security_id.in_(list(sec_map.keys())),
                            NAVHistory.date <= GRANDFATHER_FMV_DATE,
                        )
                        .order_by(NAVHistory.security_id, NAVHistory.date.desc())
                    )
                    for sid, nav in (await session.execute(stmt_nav)).all():
                        sec_isin = sec_map.get(sid)
                        if sec_isin and sec_isin not in fmv_cache and nav is not None:
                            fmv_cache[sec_isin] = nav

        def fmv_lookup(isin: str, on: date) -> Decimal | None:
            norm = (isin or "").strip().upper()
            if not norm:
                return None
            if norm in fmv_cache:
                return fmv_cache[norm]
            return _mf_fmv(norm, on)

        return fmv_lookup

    async def get_capital_gains_report(
        self,
        investor_id: int,
        fy: str,
        *,
        include_unreconciled: bool = False,
        fmv_lookup: Callable[[str, date], Decimal | None] | None = None,
    ) -> dict[str, Any]:
        """Realized capital gains report for a single financial year (e.g. '2024-25')."""
        fy_start, fy_end = india_fy_range(fy)
        async with self.session_factory() as session:
            stmt_inv = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt_inv)).scalar_one_or_none()
            if inv is None:
                raise ValueError(f"Investor {investor_id} not found")

            transactions = await self._tax_ready_transactions(
                session, investor_id, include_unreconciled=include_unreconciled
            )
            reductions = await demerger_reductions(session, investor_id)

            if fmv_lookup is None:
                all_isins = [t.security.isin for t in transactions if t.security and t.security.isin]
                fmv = await self._build_fmv_lookup(session, all_isins)
            else:
                fmv = fmv_lookup

            gain_lines = compute_gain_lines(
                transactions,
                get_policy("IN"),
                fmv_lookup=fmv,
                demerger_reductions=reductions,
            )

            in_fy = [g for g in gain_lines if fy_start <= g.disposal.sold_on <= fy_end]
            target_isins = {g.disposal.security.isin for g in in_fy if g.disposal.security and g.disposal.security.isin}
            isin_to_id: dict[str, int] = {}
            if target_isins:
                stmt_sec = select(Security.isin, Security.id).where(Security.isin.in_(list(target_isins)))
                isin_to_id = dict((await session.execute(stmt_sec)).all())

            rows: list[dict[str, Any]] = []
            stcg = Decimal("0")
            ltcg = Decimal("0")
            exempt = Decimal("0")

            for line in in_fy:
                d = line.disposal
                sale_value = (d.units * d.sale_price_per_unit).quantize(_Q2, rounding=ROUND_HALF_EVEN)
                if line.term is Term.SHORT:
                    stcg += line.gain
                elif line.term is Term.LONG:
                    ltcg += line.gain
                else:
                    exempt += line.gain

                rows.append(
                    {
                        "security_id": isin_to_id.get(d.security.isin),
                        "name": d.security.name,
                        "isin": d.security.isin or "",
                        "units": d.units,
                        "sale_value": sale_value,
                        "cost": sale_value - line.gain,
                        "gain": line.gain,
                        "term": line.term.value,
                        "acquired_on": d.acquired_on,
                        "sold_on": d.sold_on,
                        "grandfathering_unavailable": bool(line.metadata.get("grandfathering_unavailable")),
                    }
                )

            rows.sort(key=lambda r: (r["term"], r["sold_on"]))
            return {
                "fy": fy,
                "stcg_total": stcg.quantize(_Q2, rounding=ROUND_HALF_EVEN),
                "ltcg_total": ltcg.quantize(_Q2, rounding=ROUND_HALF_EVEN),
                "exempt_total": exempt.quantize(_Q2, rounding=ROUND_HALF_EVEN),
                "rows": rows,
                "disclaimer": "Capital gains report is indicative and does not constitute tax advice.",
            }

    async def list_capital_gains_by_fy(
        self,
        investor_id: int,
        *,
        include_unreconciled: bool = False,
        fmv_lookup: Callable[[str, date], Decimal | None] | None = None,
    ) -> list[dict[str, Any]]:
        """STCG/LTCG totals for every financial year with realized disposals."""
        async with self.session_factory() as session:
            stmt_inv = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt_inv)).scalar_one_or_none()
            if inv is None:
                raise ValueError(f"Investor {investor_id} not found")

            transactions = await self._tax_ready_transactions(
                session, investor_id, include_unreconciled=include_unreconciled
            )
            reductions = await demerger_reductions(session, investor_id)

            if fmv_lookup is None:
                all_isins = [t.security.isin for t in transactions if t.security and t.security.isin]
                fmv = await self._build_fmv_lookup(session, all_isins)
            else:
                fmv = fmv_lookup

            gain_lines = compute_gain_lines(
                transactions,
                get_policy("IN"),
                fmv_lookup=fmv,
                demerger_reductions=reductions,
            )

            stcg: dict[str, Decimal] = {}
            ltcg: dict[str, Decimal] = {}
            for line in gain_lines:
                fy = india_fy_label(line.disposal.sold_on)
                if line.term is Term.SHORT:
                    stcg[fy] = stcg.get(fy, Decimal("0")) + line.gain
                elif line.term is Term.LONG:
                    ltcg[fy] = ltcg.get(fy, Decimal("0")) + line.gain

            all_fys = sorted(set(stcg) | set(ltcg))
            return [
                {
                    "fy": fy,
                    "stcg": stcg.get(fy, Decimal("0")).quantize(_Q2, rounding=ROUND_HALF_EVEN),
                    "ltcg": ltcg.get(fy, Decimal("0")).quantize(_Q2, rounding=ROUND_HALF_EVEN),
                }
                for fy in all_fys
            ]

    async def get_schedule_112a(
        self,
        investor_id: int,
        fy: str,
        *,
        include_unreconciled: bool = False,
        fmv_lookup: Callable[[str, date], Decimal | None] | None = None,
    ) -> dict[str, Any]:
        """Official Schedule 112A export for an Indian financial year."""
        async with self.session_factory() as session:
            stmt_inv = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt_inv)).scalar_one_or_none()
            if inv is None:
                raise ValueError(f"Investor {investor_id} not found")

            transactions = await self._tax_ready_transactions(
                session, investor_id, include_unreconciled=include_unreconciled
            )
            reductions = await demerger_reductions(session, investor_id)

            if fmv_lookup is None:
                all_isins = [t.security.isin for t in transactions if t.security and t.security.isin]
                fmv = await self._build_fmv_lookup(session, all_isins)
            else:
                fmv = fmv_lookup

            gain_lines = compute_gain_lines(
                transactions,
                get_policy("IN"),
                fmv_lookup=fmv,
                demerger_reductions=reductions,
            )

            integrity_by_sec = {t.security: IntegrityStatus.RECONCILED for t in transactions}
            rows = compute_schedule_112a(
                gain_lines,
                fy,
                include_unreconciled=include_unreconciled,
                integrity_by_security=integrity_by_sec,
                fmv_lookup=fmv,
            )

            return {
                "fy": fy,
                "include_unreconciled": include_unreconciled,
                "row_count": len(rows),
                "columns": list(SCHEDULE_112A_CSV_COLUMNS),
                "rows": [row.to_csv_dict() for row in rows],
            }


__all__ = [
    "CapitalGainsService",
]
