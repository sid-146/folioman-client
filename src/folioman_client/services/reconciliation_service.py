"""Reconciliation service: verifies trade ledger against reported statement snapshots per (security, folio).

Updates SecurityIntegrityStatus rows, verifies tax safety for capital gains,
detects corporate action issues, and flags required opening lots.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from folioman_client.core.corporate_action_detect import (
    CachedCorporateAction,
    ReplayMatch,
    ReplayStep,
    detect_corporate_action_issues,
    strip_corporate_action_issues,
    strip_opening_lot_issues,
)
from folioman_client.core.corporate_action_subject import CorpActionType
from folioman_client.core.corporate_actions import (
    CorporateActionApplyEvent,
    apply_corporate_action_events,
    held_units_asof,
)
from folioman_client.core.fifo import net_units_from_transactions
from folioman_client.core.models.holding import HoldingSource
from folioman_client.core.models.security import SecurityType
from folioman_client.core.reconciliation import (
    TOLERANCE,
    IntegrityStatus,
    ReconciliationResult,
    reconcile,
)
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AppliedCorporateAction,
    CorporateActionReference,
    Folio,
    Holding,
    Investor,
    PartialBlock,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)
from folioman_client.services.mappers import (
    to_core_holding,
    to_core_security,
    to_core_transaction,
)
from folioman_client.services.projected_ledger import compute_ledger

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _parsed_ratio(row: CorporateActionReference) -> tuple[int, int] | None:
    raw = (row.parsed_json or {}).get("ratio")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            a, b = int(raw[0]), int(raw[1])
            if b != 0:
                return (a, b)
        except (TypeError, ValueError):
            pass
    return None


def _dedupe_scaling(
    actions: list[CachedCorporateAction],
) -> list[CachedCorporateAction]:
    seen: set[tuple[date, Decimal]] = set()
    deduped: list[CachedCorporateAction] = []
    for a in actions:
        if (
            a.parsed_type
            not in {CorpActionType.BONUS.value, CorpActionType.SPLIT.value}
            or a.needs_review
            or a.unit_multiplier is None
            or a.reference_id is None
        ):
            continue
        key = (a.ex_date, a.unit_multiplier.normalize())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    return deduped


def _replay_corporate_actions(
    txns: list,
    security: Security,
    cached_actions: list[CachedCorporateAction],
    applied_refs: set[str],
) -> ReplayMatch | None:
    deduped = [
        a
        for a in sorted(_dedupe_scaling(cached_actions), key=lambda a: a.ex_date)
        if f"ca-ref:{a.reference_id}" not in applied_refs
    ]
    if not deduped:
        return None
    core_sec = to_core_security(security)
    running = list(txns)
    steps: list[ReplayStep] = []
    try:
        for a in deduped:
            event = CorporateActionApplyEvent(
                kind=CorpActionType(a.parsed_type),
                ex_date=a.ex_date,
                security=core_sec,
                unit_multiplier=a.unit_multiplier,
                bonus_ratio=a.bonus_ratio,
                source_ref=f"ca-ref:{a.reference_id}",
            )
            before = held_units_asof(running, core_sec, a.ex_date)
            running = apply_corporate_action_events(running, [event])
            after = held_units_asof(running, core_sec, a.ex_date + timedelta(days=1))
            steps.append(ReplayStep(action=a, units_before=before, units_after=after))
    except (ValueError, KeyError):
        return None
    return ReplayMatch(replayed_units=net_units_from_transactions(running), steps=steps)


class ReconciliationService:
    """Async service managing trade ledger and statement holding reconciliations."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)

    async def _cached_actions_for_security(
        self, session: AsyncSession, security: Security
    ) -> list[CachedCorporateAction]:
        if (security.security_type or "").upper() != SecurityType.EQUITY.value.upper():
            return []
        stmt = select(CorporateActionReference).where(
            (CorporateActionReference.security_id == security.id)
            | (CorporateActionReference.isin == security.isin)
        )
        rows = (await session.execute(stmt)).scalars().all()
        cached: dict[int, CachedCorporateAction] = {}
        for r in rows:
            cached[r.id] = CachedCorporateAction(
                ex_date=r.ex_date,
                subject=r.subject,
                parsed_type=r.parsed_type,
                unit_multiplier=r.unit_multiplier,
                needs_review=r.needs_review,
                reference_id=r.id,
                bonus_ratio=_parsed_ratio(r),
            )
        return list(cached.values())

    async def reconcile_security_folio(
        self,
        session: AsyncSession,
        investor_id: int,
        security_id: int,
        folio_id: int,
        *,
        acknowledge: bool = False,
        clear_acknowledgement: bool = False,
    ) -> SecurityIntegrityStatus | None:
        """Reconcile one (investor, security, folio) position and upsert its integrity status."""
        security = await session.get(Security, security_id)
        if security is None:
            return None

        # 1. Projected cost-basis transactions
        txns = await compute_ledger(
            session, investor_id, security_id, folio_id=folio_id
        )

        # 2. Observed holding snapshots
        holdings_stmt = (
            select(Holding)
            .options(selectinload(Holding.security), selectinload(Holding.folio))
            .where(
                Holding.investor_id == investor_id,
                Holding.security_id == security_id,
                Holding.folio_id == folio_id,
            )
        )
        # Drop 0-unit eCAS holding if no transactions exist
        txns_exist = bool(
            await session.scalar(
                select(Transaction.id)
                .where(
                    Transaction.investor_id == investor_id,
                    Transaction.security_id == security_id,
                    Transaction.folio_id == folio_id,
                )
                .limit(1)
            )
        )
        if not txns_exist:
            holdings_stmt = holdings_stmt.where(Holding.units > 0)

        holdings_db = (await session.execute(holdings_stmt)).scalars().all()
        holdings = [to_core_holding(h) for h in holdings_db]

        # Superseded CAS_PDF snapshots at or before latest transaction date are dropped
        if txns:
            latest_txn = max(t.date for t in txns)
            holdings = [
                h
                for h in holdings
                if not (
                    h.source is HoldingSource.CAS_PDF and h.as_of_date <= latest_txn
                )
            ]

        # 3. Existing integrity row & acknowledgement handling
        status_stmt = select(SecurityIntegrityStatus).where(
            SecurityIntegrityStatus.investor_id == investor_id,
            SecurityIntegrityStatus.security_id == security_id,
            SecurityIntegrityStatus.folio_id == folio_id,
        )
        existing = (await session.execute(status_stmt)).scalar_one_or_none()
        already_acknowledged = bool(
            existing and existing.status == IntegrityStatus.USER_ACKNOWLEDGED.value
        )
        user_acknowledged = (
            False if clear_acknowledgement else (already_acknowledged or acknowledge)
        )

        # 4. Partial blocks & display transactions
        pb_stmt = select(PartialBlock).where(
            PartialBlock.investor_id == investor_id,
            PartialBlock.security_id == security_id,
            PartialBlock.folio_id == folio_id,
        )
        partial = (await session.execute(pb_stmt)).scalar_one_or_none()

        display_txns = [
            to_core_transaction(t)
            for t in (
                await session.execute(
                    select(Transaction)
                    .options(
                        selectinload(Transaction.security),
                        selectinload(Transaction.folio),
                    )
                    .where(
                        Transaction.investor_id == investor_id,
                        Transaction.security_id == security_id,
                        Transaction.folio_id == folio_id,
                    )
                )
            )
            .scalars()
            .all()
        ]

        # 5. Core reconciliation
        result = reconcile(
            txns or None, holdings or None, user_acknowledged=user_acknowledged
        )

        if partial is not None and not txns and display_txns:
            issue_incomplete = {
                "type": "incomplete_history",
                "reason": "orphan_sell",
                "missing_prior_units": str(partial.opening_units),
            }
            if result is None:
                result = ReconciliationResult(
                    status=IntegrityStatus.SNAPSHOT_ONLY,
                    tax_safe=False,
                    units_from_transactions=None,
                    units_from_holdings=None,
                    issues=[issue_incomplete],
                )
            else:
                clean_issues = [
                    i for i in result.issues if i.get("type") != "incomplete_history"
                ]
                clean_issues.insert(0, issue_incomplete)
                result = result.model_copy(
                    update={"tax_safe": False, "issues": clean_issues}
                )

        incomplete_history = partial is not None or (
            result is not None
            and result.units_from_transactions is not None
            and result.units_from_transactions < 0
        )

        # 6. Corporate Action & Opening Lot detection for Equities
        if (
            result is not None
            and (security.security_type or "").upper()
            == SecurityType.EQUITY.value.upper()
        ):
            cached_actions = await self._cached_actions_for_security(session, security)
            applied_refs_stmt = select(AppliedCorporateAction.source_ref).where(
                AppliedCorporateAction.investor_id == investor_id,
                AppliedCorporateAction.security_id == security_id,
            )
            applied_refs = set(
                (await session.execute(applied_refs_stmt)).scalars().all()
            )

            replay_base = (
                await compute_ledger(
                    session,
                    investor_id,
                    security_id,
                    folio_id=folio_id,
                    include_incomplete=True,
                )
                or display_txns
            )

            replay = None
            net = result.units_from_transactions
            holding_units = result.units_from_holdings
            has_gap = (
                net is not None
                and holding_units is not None
                and holding_units - net > TOLERANCE
            )
            needs_replay = (
                incomplete_history or (net is not None and net < _ZERO) or has_gap
            )
            if replay_base and needs_replay and _dedupe_scaling(cached_actions):
                replay = _replay_corporate_actions(
                    replay_base, security, cached_actions, applied_refs
                )

            ca_issues = detect_corporate_action_issues(
                net_units=net,
                holding_units=holding_units,
                incomplete_history=incomplete_history,
                cached_actions=cached_actions,
                replay=replay,
            )
            issues = strip_corporate_action_issues(result.issues)
            if ca_issues:
                if ca_issues[0].get("type") == "corporate_action_suggestion":
                    issues = [
                        i for i in issues if i.get("type") != "incomplete_history"
                    ]
                issues = [*issues, *ca_issues]
            result = result.model_copy(update={"issues": issues})

            # Check opening lot
            base_ref = f"opening-lot:{folio_id}:{security_id}"
            has_opening_lot = bool(
                await session.scalar(
                    select(Transaction.id)
                    .where(
                        Transaction.investor_id == investor_id,
                        Transaction.security_id == security_id,
                        Transaction.folio_id == folio_id,
                        Transaction.source_ref.startswith(base_ref),
                    )
                    .limit(1)
                )
            )
            if has_opening_lot:
                clean_issues = [
                    i
                    for i in result.issues
                    if i.get("type")
                    not in ("opening_lot_needed", "opening_lot_recorded")
                ]
                clean_issues.append({"type": "opening_lot_recorded"})
                result = result.model_copy(update={"issues": clean_issues})
            elif (
                result.status is IntegrityStatus.SNAPSHOT_ONLY
                and result.units_from_holdings
                and result.units_from_holdings > 0
            ):
                clean_issues = strip_opening_lot_issues(result.issues)
                clean_issues = [
                    i
                    for i in clean_issues
                    if not (
                        i.get("type") == "corporate_action_manual"
                        and i.get("reason") == "snapshot_only"
                    )
                ]
                clean_issues.append(
                    {
                        "type": "opening_lot_needed",
                        "holding_units": str(result.units_from_holdings),
                        "classifications": [
                            "ipo_allotment",
                            "transfer_in",
                            "demerger_result",
                        ],
                    }
                )
                result = result.model_copy(update={"issues": clean_issues})

        # 7. Persist or prune
        if result is None:
            if existing:
                await session.delete(existing)
                await session.flush()
            return None

        ledger_through = max((t.date for t in txns), default=None)
        if ledger_through is None and display_txns:
            ledger_through = max(t.date for t in display_txns)
        snapshot_as_of = max((h.as_of_date for h in holdings), default=None)

        if existing is None:
            existing = SecurityIntegrityStatus(
                investor_id=investor_id,
                security_id=security_id,
                folio_id=folio_id,
                status=result.status.value,
                tax_safe=result.tax_safe,
                units_from_transactions=result.units_from_transactions,
                units_from_holdings=result.units_from_holdings,
                issues_json=result.issues,
                ledger_through=ledger_through,
                snapshot_as_of=snapshot_as_of,
                last_reconciled_at=datetime.now(timezone.utc),
            )
            session.add(existing)
        else:
            existing.status = result.status.value
            existing.tax_safe = result.tax_safe
            existing.units_from_transactions = result.units_from_transactions
            existing.units_from_holdings = result.units_from_holdings
            existing.issues_json = result.issues
            existing.ledger_through = ledger_through
            existing.snapshot_as_of = snapshot_as_of
            existing.last_reconciled_at = datetime.now(timezone.utc)

        await session.flush()
        return existing

    async def reconcile_security(
        self, session: AsyncSession, investor_id: int, security_id: int
    ) -> list[SecurityIntegrityStatus]:
        """Reconcile every folio holding this security, pruning stale statuses."""
        txn_folios = (
            (
                await session.execute(
                    select(Transaction.folio_id)
                    .where(
                        Transaction.investor_id == investor_id,
                        Transaction.security_id == security_id,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        holding_folios = (
            (
                await session.execute(
                    select(Holding.folio_id)
                    .where(
                        Holding.investor_id == investor_id,
                        Holding.security_id == security_id,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

        folio_ids = {f for f in set(txn_folios) | set(holding_folios) if f is not None}
        statuses: list[SecurityIntegrityStatus] = []
        for fid in folio_ids:
            st = await self.reconcile_security_folio(
                session, investor_id, security_id, fid
            )
            if st is not None:
                statuses.append(st)

        # Prune removed folios
        await session.execute(
            delete(SecurityIntegrityStatus).where(
                SecurityIntegrityStatus.investor_id == investor_id,
                SecurityIntegrityStatus.security_id == security_id,
                (
                    SecurityIntegrityStatus.folio_id.not_in(list(folio_ids))
                    if folio_ids
                    else True
                ),
            )
        )
        await session.flush()
        return statuses

    async def reconcile_investor(self, investor_id: int) -> dict[str, Any]:
        """Re-reconcile every security for a single investor."""
        await init_schema(self.engine)

        summary = {
            "investor_id": investor_id,
            "securities_reconciled": 0,
            "statuses_count": 0,
            "tax_safe_count": 0,
            "mismatch_count": 0,
        }

        async with self.session_factory() as session:
            txn_sec = (
                (
                    await session.execute(
                        select(Transaction.security_id)
                        .where(Transaction.investor_id == investor_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )
            holding_sec = (
                (
                    await session.execute(
                        select(Holding.security_id)
                        .where(Holding.investor_id == investor_id)
                        .distinct()
                    )
                )
                .scalars()
                .all()
            )

            security_ids = set(txn_sec) | set(holding_sec)
            for sid in security_ids:
                statuses = await self.reconcile_security(session, investor_id, sid)
                summary["securities_reconciled"] += 1
                summary["statuses_count"] += len(statuses)
                for s in statuses:
                    if s.tax_safe:
                        summary["tax_safe_count"] += 1
                    if s.status == IntegrityStatus.MISMATCH.value:
                        summary["mismatch_count"] += 1

            await session.commit()

        return summary

    async def reconcile_all(self, user_id: str | None = None) -> dict[str, Any]:
        """Recompute integrity statuses across all investors in the active database."""
        await init_schema(self.engine)

        summary = {
            "investors_count": 0,
            "statuses_count": 0,
            "tax_safe_count": 0,
            "mismatch_count": 0,
        }

        async with self.session_factory() as session:
            stmt = select(Investor.id)
            if user_id:
                stmt = stmt.where(Investor.user_id == user_id)
            investor_ids = (await session.execute(stmt)).scalars().all()

        for inv_id in investor_ids:
            res = await self.reconcile_investor(inv_id)
            summary["investors_count"] += 1
            summary["statuses_count"] += res["statuses_count"]
            summary["tax_safe_count"] += res["tax_safe_count"]
            summary["mismatch_count"] += res["mismatch_count"]

        return summary

    async def acknowledge_mismatch(
        self, investor_id: int, security_id: int, folio_id: int
    ) -> dict[str, Any]:
        """Acknowledge a unit mismatch for a (security, folio) position."""
        async with self.session_factory() as session:
            status = await self.reconcile_security_folio(
                session, investor_id, security_id, folio_id, acknowledge=True
            )
            await session.commit()
            if status is None:
                raise ValueError("Position has no data to reconcile.")
            return {
                "status": status.status,
                "tax_safe": status.tax_safe,
                "issues": status.issues_json,
            }

    async def clear_acknowledgement(
        self, investor_id: int, security_id: int, folio_id: int
    ) -> dict[str, Any]:
        """Clear user acknowledgement, reverting to the position's genuine status."""
        async with self.session_factory() as session:
            status = await self.reconcile_security_folio(
                session, investor_id, security_id, folio_id, clear_acknowledgement=True
            )
            await session.commit()
            if status is None:
                raise ValueError("Position has no data to reconcile.")
            return {
                "status": status.status,
                "tax_safe": status.tax_safe,
                "issues": status.issues_json,
            }


__all__ = ["ReconciliationService"]
