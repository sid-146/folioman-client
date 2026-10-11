"""Corporate actions service: fetching exchange announcements, caching, and applying adjustments."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import logging
from typing import Any, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from folioman_client.core.corporate_action_subject import (
    CorpActionType,
    ParsedCorporateAction,
    parse_subject,
)
from folioman_client.core.models.security import SecurityType
from folioman_client.core.price_feeds import corporate_actions_fetch
from folioman_client.core.price_feeds.corporate_actions_fetch import (
    CorporateActionFetchError,
    CorporateActionThrottled,
    _normalize_subject,
)
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AppliedCorporateAction,
    CorporateActionReference,
    Folio,
    Investor,
    Security,
)

logger = logging.getLogger(__name__)


def _parsed_to_dict(parsed: ParsedCorporateAction) -> dict[str, Any]:
    return {
        "type": parsed.type.value,
        "raw": parsed.raw,
        "ratio": list(parsed.ratio) if parsed.ratio else None,
        "unit_multiplier": (
            str(parsed.unit_multiplier) if parsed.unit_multiplier is not None else None
        ),
        "amount": str(parsed.amount) if parsed.amount is not None else None,
        "face_value_from": (
            str(parsed.face_value_from) if parsed.face_value_from is not None else None
        ),
        "face_value_to": (
            str(parsed.face_value_to) if parsed.face_value_to is not None else None
        ),
        "needs_review": parsed.needs_review,
    }


class CorporateActionService:
    """Service to fetch, cache, and apply corporate action events."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)

    async def _upsert_action_reference(
        self,
        session: AsyncSession,
        security_id: int | None,
        event: Any,
    ) -> CorporateActionReference:
        parsed = parse_subject(event.subject)
        subject_norm = _normalize_subject(event.subject)
        isin = (event.isin or "").strip().upper()
        symbol = (event.symbol or "").strip().upper()

        # Find existing reference row
        stmt = select(CorporateActionReference).where(
            CorporateActionReference.ex_date == event.ex_date,
            CorporateActionReference.subject == subject_norm,
            CorporateActionReference.exchange == event.exchange,
        )
        if isin:
            stmt = stmt.where(CorporateActionReference.isin == isin)
        else:
            stmt = stmt.where(CorporateActionReference.symbol == symbol)

        ref = (await session.execute(stmt)).scalar_one_or_none()
        if ref is None:
            ref = CorporateActionReference(
                security_id=security_id,
                isin=isin,
                symbol=symbol,
                series=event.series or "",
                exchange=event.exchange or "",
                ex_date=event.ex_date,
                record_date=event.record_date,
                subject=subject_norm,
                parsed_type=parsed.type.value,
                unit_multiplier=parsed.unit_multiplier,
                amount=parsed.amount,
                parsed_json=_parsed_to_dict(parsed),
                needs_review=parsed.needs_review,
                source=event.exchange.lower() if event.exchange else "",
            )
            session.add(ref)
        else:
            if security_id and not ref.security_id:
                ref.security_id = security_id
            ref.record_date = event.record_date
            ref.parsed_type = parsed.type.value
            ref.unit_multiplier = parsed.unit_multiplier
            ref.amount = parsed.amount
            ref.parsed_json = _parsed_to_dict(parsed)
            ref.needs_review = parsed.needs_review

        await session.flush()
        return ref

    async def refresh_corporate_actions(
        self,
        *,
        security_ids: list[int] | None = None,
        since_year: int = 2016,
    ) -> dict[str, Any]:
        """Fetch and cache corporate action history for equity securities from NSE/BSE feeds.

        Args:
            security_ids: Optional subset of security IDs to refresh. If None, queries all equities.
            since_year: Earliest year to pull history back to (defaults to 2016).

        Returns:
            Dictionary summary with total actions fetched, updated, and error counts.
        """
        await init_schema(self.engine)

        summary: dict[str, Any] = {
            "securities_checked": 0,
            "actions_fetched": 0,
            "errors": 0,
        }

        async with self.session_factory() as session:
            stmt = select(Security).where(
                Security.security_type == SecurityType.EQUITY.value.upper(),
                Security.symbol != "",
            )
            if security_ids:
                stmt = stmt.where(Security.id.in_(security_ids))

            securities = (await session.execute(stmt)).scalars().all()
            summary["securities_checked"] = len(securities)

            if not securities:
                return summary

            start_date = date(since_year, 1, 1)
            end_date = date.today()

            def _fetch_actions_sync(sym: str, exch: str, isin: str):
                nse = corporate_actions_fetch.warmed_nse_client()
                bse = corporate_actions_fetch.warmed_bse_client()
                try:
                    return corporate_actions_fetch.fetch_corporate_actions(
                        sym,
                        exchange=exch,
                        isin=isin,
                        start=start_date,
                        end=end_date,
                        nse=nse,
                        bse=bse,
                    )
                finally:
                    nse.close()
                    bse.close()

            for sec in securities:
                try:
                    events = await asyncio.to_thread(
                        _fetch_actions_sync,
                        sec.symbol,
                        sec.exchange,
                        sec.isin,
                    )
                    for event in events:
                        await self._upsert_action_reference(session, sec.id, event)
                        summary["actions_fetched"] += 1

                    sec.corporate_actions_synced_at = datetime.now(timezone.utc)
                except CorporateActionThrottled:
                    logger.warning(
                        "Exchange throttled corporate action fetch; stopping batch pass."
                    )
                    summary["errors"] += 1
                    break
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch corporate actions for %s (%s): %s",
                        sec.symbol,
                        sec.isin,
                        exc,
                    )
                    summary["errors"] += 1

            await session.commit()

        return summary

    async def apply_corporate_action(
        self,
        investor_id: int,
        folio_id: int,
        reference_id: int,
    ) -> dict[str, Any]:
        """Apply a cached corporate action (BONUS or SPLIT) to an investor folio.

        Records the action in the applied_corporate_actions log (preserving the immutable
        transaction ledger) and returns the created event details.
        """
        await init_schema(self.engine)

        async with self.session_factory() as session:
            # 1. Load reference action
            ref = await session.get(CorporateActionReference, reference_id)
            if ref is None:
                raise ValueError(f"CorporateActionReference {reference_id} not found.")

            if ref.needs_review:
                raise ValueError(
                    f"Action {reference_id} is marked as needs_review and cannot be auto-applied."
                )

            if ref.parsed_type not in (
                CorpActionType.BONUS.value,
                CorpActionType.SPLIT.value,
            ):
                raise ValueError(
                    f"Action type '{ref.parsed_type}' is not auto-applicable. Only bonus and split are supported."
                )

            # 2. Resolve security
            security_id = ref.security_id
            if not security_id:
                # Find matching security by ISIN or symbol
                stmt = select(Security).where(
                    (Security.isin == ref.isin) | (Security.symbol == ref.symbol)
                )
                sec = (await session.execute(stmt)).scalars().first()
                if not sec:
                    raise ValueError(
                        f"No security found in database matching action {ref.isin or ref.symbol}."
                    )
                security_id = sec.id

            # 3. Check if already applied
            source_ref = f"ca-ref:{ref.id}"
            exist_stmt = select(AppliedCorporateAction).where(
                AppliedCorporateAction.investor_id == investor_id,
                AppliedCorporateAction.folio_id == folio_id,
                AppliedCorporateAction.security_id == security_id,
                AppliedCorporateAction.source_ref == source_ref,
            )
            existing = (await session.execute(exist_stmt)).scalar_one_or_none()
            if existing:
                return {
                    "applied": False,
                    "reason": "already_applied",
                    "action_id": existing.id,
                }

            # 4. Create AppliedCorporateAction row
            ratio_a = None
            ratio_b = None
            raw_ratio = (ref.parsed_json or {}).get("ratio")
            if isinstance(raw_ratio, (list, tuple)) and len(raw_ratio) == 2:
                ratio_a, ratio_b = int(raw_ratio[0]), int(raw_ratio[1])

            aca = AppliedCorporateAction(
                investor_id=investor_id,
                folio_id=folio_id,
                security_id=security_id,
                kind=ref.parsed_type,
                ex_date=ref.ex_date,
                unit_multiplier=ref.unit_multiplier,
                bonus_ratio_a=ratio_a,
                bonus_ratio_b=ratio_b,
                dividend_per_share=ref.amount,
                source_ref=source_ref,
                params_json=ref.parsed_json or {},
            )
            session.add(aca)
            await session.commit()

            return {
                "applied": True,
                "action_id": aca.id,
                "kind": aca.kind,
                "ex_date": aca.ex_date.isoformat(),
                "unit_multiplier": str(aca.unit_multiplier or ""),
            }

    async def list_references(
        self,
        *,
        security_id: int | None = None,
        isin: str | None = None,
        symbol: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """List cached corporate action announcements matching search criteria."""
        async with self.session_factory() as session:
            stmt = select(CorporateActionReference).order_by(
                CorporateActionReference.ex_date.desc()
            )
            if security_id is not None:
                stmt = stmt.where(CorporateActionReference.security_id == security_id)
            if isin:
                stmt = stmt.where(CorporateActionReference.isin == isin.strip().upper())
            if symbol:
                stmt = stmt.where(
                    CorporateActionReference.symbol == symbol.strip().upper()
                )
            if kind:
                stmt = stmt.where(CorporateActionReference.parsed_type == kind.lower())

            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "isin": r.isin,
                    "symbol": r.symbol,
                    "ex_date": r.ex_date.isoformat(),
                    "record_date": r.record_date.isoformat() if r.record_date else None,
                    "subject": r.subject,
                    "type": r.parsed_type,
                    "unit_multiplier": (
                        str(r.unit_multiplier)
                        if r.unit_multiplier is not None
                        else None
                    ),
                    "amount": str(r.amount) if r.amount is not None else None,
                    "needs_review": r.needs_review,
                }
                for r in rows
            ]


__all__ = ["CorporateActionService"]
