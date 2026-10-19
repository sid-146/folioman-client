"""Project the as-traded ledger through applied corporate actions in memory.

Derives the adjusted view (split-scaled units, merged lots, bonus shares)
by replaying AppliedCorporateAction events over raw Transaction rows.
No database rows are mutated.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from folioman_client.core.corporate_action_subject import CorpActionType
from folioman_client.core.corporate_actions import (
    CorporateActionApplyEvent,
    apply_corporate_action_events,
)
from folioman_client.core.fifo import net_intraday_offsets
from folioman_client.core.models.transaction import Transaction as CoreTransaction
from folioman_client.db.models import (
    AppliedCorporateAction,
    Security,
    Transaction,
)
from folioman_client.services.mappers import to_core_security, to_core_transaction


def security_key(sec: Security) -> str:
    """Stable identity for grouping projected core rows back to a DB security.

    Works on both core and DB Security (ISIN for equity, AMFI for MF).
    """
    return sec.isin or getattr(sec, "amfi_code", "") or sec.symbol or sec.name


async def demerger_reductions(
    session: AsyncSession, investor_id: int, *, folio_id: int | None = None
) -> dict[str, list]:
    """Each parent security's demerger cost reductions, keyed by security identity."""
    stmt = (
        select(AppliedCorporateAction)
        .options(selectinload(AppliedCorporateAction.security))
        .where(
            AppliedCorporateAction.investor_id == investor_id,
            AppliedCorporateAction.kind == CorpActionType.DEMERGER.value,
        )
    )
    if folio_id is not None:
        stmt = stmt.where(
            (AppliedCorporateAction.folio_id == folio_id)
            | (AppliedCorporateAction.folio_id.is_(None))
        )
    events = (await session.execute(stmt)).scalars().all()
    out: dict[str, list] = {}
    for aca in events:
        sec = aca.security
        ident = sec.isin or sec.symbol or sec.name
        by_date = {
            date.fromisoformat(iso): Decimal(str(cost))
            for iso, cost in (aca.params or {}).get("reductions", {}).items()
        }
        if by_date:
            out.setdefault(ident, []).append((aca.ex_date, by_date))
    return out


def event_from_applied(aca: AppliedCorporateAction) -> CorporateActionApplyEvent:
    """Reconstruct a core CorporateActionApplyEvent from a stored AppliedCorporateAction row."""
    kind = CorpActionType(aca.kind)
    if kind is CorpActionType.DEMERGER:
        return CorporateActionApplyEvent(
            kind=kind,
            ex_date=aca.ex_date,
            security=to_core_security(aca.security),
            source_ref=aca.source_ref or "",
        )
    if kind is CorpActionType.MERGER:
        acquirer = to_core_security(aca.counterparty_security)
        return CorporateActionApplyEvent(
            kind=kind,
            ex_date=aca.ex_date,
            security=acquirer,
            merger_old_security=to_core_security(aca.security),
            merger_new_security=acquirer,
            merger_ratio=aca.merger_ratio,
            source_ref=aca.source_ref or "",
        )

    bonus_ratio = (
        (aca.bonus_ratio_a, aca.bonus_ratio_b)
        if aca.bonus_ratio_a is not None and aca.bonus_ratio_b is not None
        else None
    )
    return CorporateActionApplyEvent(
        kind=kind,
        ex_date=aca.ex_date,
        security=to_core_security(aca.security),
        unit_multiplier=aca.unit_multiplier,
        bonus_ratio=bonus_ratio,
        dividend_per_share=aca.dividend_per_share,
        rights_units=aca.units,
        rights_price=aca.price,
        source_ref=aca.source_ref or "",
    )


def _replay(
    raw: list[CoreTransaction],
    events: Sequence[AppliedCorporateAction],
    as_of: date | None = None,
) -> list[CoreTransaction]:
    """Apply the corporate action event log over raw transactions."""
    if as_of is not None:
        events = [e for e in events if e.ex_date <= as_of]
    apply_events = [event_from_applied(aca) for aca in events]
    adjusted = apply_corporate_action_events(raw, apply_events)
    if as_of is not None:
        adjusted = [t for t in adjusted if t.date <= as_of]
    return adjusted


async def compute_ledger(
    session: AsyncSession,
    investor_id: int,
    security_id: int,
    *,
    folio_id: int | None = None,
    as_of: date | None = None,
    include_incomplete: bool = False,
) -> list[CoreTransaction]:
    """The projected cost-basis ledger for one (investor, security, [folio]).

    Replays applied corporate actions (and handles acquirer lot absorption from mergers).
    """
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.security), selectinload(Transaction.folio))
        .where(
            Transaction.investor_id == investor_id,
            Transaction.security_id == security_id,
        )
    )
    if folio_id is not None:
        stmt = stmt.where(Transaction.folio_id == folio_id)
    if not include_incomplete:
        stmt = stmt.where(Transaction.cost_basis_complete.is_(True))

    txns = (await session.execute(stmt)).scalars().all()
    core_txns = net_intraday_offsets([to_core_transaction(t) for t in txns])

    ca_stmt = (
        select(AppliedCorporateAction)
        .options(
            selectinload(AppliedCorporateAction.security),
            selectinload(AppliedCorporateAction.counterparty_security),
        )
        .where(
            AppliedCorporateAction.investor_id == investor_id,
            (AppliedCorporateAction.security_id == security_id)
            | (AppliedCorporateAction.counterparty_security_id == security_id),
        )
    )
    if folio_id is not None:
        ca_stmt = ca_stmt.where(
            (AppliedCorporateAction.folio_id == folio_id)
            | (AppliedCorporateAction.folio_id.is_(None))
        )

    events = (await session.execute(ca_stmt)).scalars().all()

    # If this security absorbed lots from a merger target, fetch the merged-away security's raw txns
    for aca in events:
        if (
            aca.kind == CorpActionType.MERGER.value
            and aca.counterparty_security_id == security_id
        ):
            stmt_merged = (
                select(Transaction)
                .options(
                    selectinload(Transaction.security), selectinload(Transaction.folio)
                )
                .where(
                    Transaction.investor_id == investor_id,
                    Transaction.security_id == aca.security_id,
                )
            )
            if folio_id is not None:
                stmt_merged = stmt_merged.where(Transaction.folio_id == folio_id)
            if not include_incomplete:
                stmt_merged = stmt_merged.where(
                    Transaction.cost_basis_complete.is_(True)
                )

            merged_raw = (await session.execute(stmt_merged)).scalars().all()
            core_txns = net_intraday_offsets(
                core_txns + [to_core_transaction(t) for t in merged_raw]
            )

    return _replay(core_txns, events, as_of=as_of)


async def projected_transactions(
    session: AsyncSession,
    investor_id: int,
    *,
    folio_id: int | None = None,
    as_of: date | None = None,
    include_incomplete: bool = False,
) -> list[CoreTransaction]:
    """The entire investor (or one folio) cost-basis ledger with corporate actions replayed."""
    stmt = (
        select(Transaction)
        .options(selectinload(Transaction.security), selectinload(Transaction.folio))
        .where(Transaction.investor_id == investor_id)
    )
    if folio_id is not None:
        stmt = stmt.where(Transaction.folio_id == folio_id)
    if not include_incomplete:
        stmt = stmt.where(Transaction.cost_basis_complete.is_(True))

    txns = (await session.execute(stmt)).scalars().all()
    core_txns = net_intraday_offsets([to_core_transaction(t) for t in txns])

    ca_stmt = (
        select(AppliedCorporateAction)
        .options(
            selectinload(AppliedCorporateAction.security),
            selectinload(AppliedCorporateAction.counterparty_security),
        )
        .where(AppliedCorporateAction.investor_id == investor_id)
    )
    if folio_id is not None:
        ca_stmt = ca_stmt.where(
            (AppliedCorporateAction.folio_id == folio_id)
            | (AppliedCorporateAction.folio_id.is_(None))
        )

    events = (await session.execute(ca_stmt)).scalars().all()
    return _replay(core_txns, events, as_of=as_of)


__all__ = [
    "compute_ledger",
    "demerger_reductions",
    "event_from_applied",
    "projected_transactions",
    "security_key",
]
