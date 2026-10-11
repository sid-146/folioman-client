"""Equity and bond symbol resolution service for demat holdings.

Resolves missing NSE/BSE trading symbols for securities imported by ISIN only,
using the active reference master database (ref_isins) and casparser-isin.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.core.models.security import SecurityType
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import ISINReference, Security
from folioman_client.services.nav_service import NAVService

logger = logging.getLogger(__name__)

_QUOTE_TYPES = {
    SecurityType.EQUITY.value.upper(),
    SecurityType.ETF.value.upper(),
    SecurityType.BOND.value.upper(),
}


class EquitySymbolService:
    """Service to repair and resolve exchange trading symbols for demat holdings."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)

    async def resolve_symbols(
        self,
        *,
        dry_run: bool = False,
        backfill: bool = False,
        force_backfill: bool = False,
    ) -> dict[str, Any]:
        """Resolve missing trading symbols for demat securities.

        Args:
            dry_run: If True, identifies matches without persisting to database.
            backfill: If True, automatically backfills historical prices for newly resolved securities.
            force_backfill: If True, backfills full history even if some prices exist.

        Returns:
            Summary dictionary with matched, unmatched, updated counts, and optional backfill stats.
        """
        await init_schema(self.engine)

        summary: dict[str, Any] = {
            "unresolved_count": 0,
            "matched_count": 0,
            "unmatched_count": 0,
            "updated_count": 0,
            "matched": [],
            "unmatched": [],
            "backfill": None,
        }

        async with self.session_factory() as session:
            # 1. Find all quote-type securities with an ISIN but empty symbol
            stmt = select(Security).where(
                Security.security_type.in_(_QUOTE_TYPES),
                Security.symbol == "",
                Security.isin != "",
            )
            securities = (await session.execute(stmt)).scalars().all()
            if not securities:
                logger.info("No securities need symbol resolution.")
                return summary

            summary["unresolved_count"] = len(securities)
            isin_map: dict[str, Security] = {
                s.isin.strip().upper(): s for s in securities
            }
            matched_symbols: dict[str, dict[str, str]] = {}

            # 2. Try looking up in the database ref_isins table first
            ref_stmt = select(ISINReference).where(
                ISINReference.isin.in_(list(isin_map.keys()))
            )
            ref_rows = (await session.execute(ref_stmt)).scalars().all()
            for r in ref_rows:
                if r.symbol:
                    matched_symbols[r.isin] = {
                        "symbol": r.symbol.upper(),
                        "exchange": (r.exchange or "NSE").upper(),
                    }

            # 3. Fallback: try casparser.parsers._isin.batch_equity_symbols if available
            unmatched_isins = [i for i in isin_map if i not in matched_symbols]
            if unmatched_isins:
                try:
                    from casparser.parsers._isin import batch_equity_symbols

                    cp_matches = batch_equity_symbols(unmatched_isins) or {}
                    for isin, sym in cp_matches.items():
                        if sym:
                            matched_symbols[isin] = {
                                "symbol": sym.upper(),
                                "exchange": "NSE",
                            }
                except (ImportError, Exception) as exc:
                    logger.debug("casparser batch_equity_symbols unavailable: %s", exc)

            # 4. Apply updates
            resolved_security_ids: list[int] = []
            for isin, sec in isin_map.items():
                if isin in matched_symbols:
                    info = matched_symbols[isin]
                    sym = info["symbol"]
                    exch = info["exchange"]
                    summary["matched"].append(
                        {
                            "id": sec.id,
                            "name": sec.name,
                            "isin": isin,
                            "symbol": sym,
                            "exchange": exch,
                        }
                    )
                    resolved_security_ids.append(sec.id)
                    if not dry_run:
                        sec.symbol = sym
                        sec.exchange = exch
                        summary["updated_count"] += 1
                else:
                    summary["unmatched"].append(
                        {"id": sec.id, "name": sec.name, "isin": isin}
                    )

            summary["matched_count"] = len(summary["matched"])
            summary["unmatched_count"] = len(summary["unmatched"])

            if not dry_run:
                await session.commit()

        # 5. Optionally backfill price history for resolved securities
        if backfill and resolved_security_ids and not dry_run:
            logger.info(
                "Triggering historical price backfill for %d resolved securities...",
                len(resolved_security_ids),
            )
            nav_svc = NAVService(engine=self.engine)
            summary["backfill"] = await nav_svc.backfill_navs(
                security_ids=resolved_security_ids,
                force=force_backfill,
            )

        return summary


__all__ = ["EquitySymbolService"]
