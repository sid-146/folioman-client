"""Valuation and performance engine for Folioman Client.

Ported from Folioman: calculates daily portfolio valuations, mark-to-market holdings,
asset/AMC/category allocations, XIRR money-weighted returns, trailing period returns,
and contiguous daily InvestorValue time series.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from folioman_client.core.corporate_actions import held_units_asof
from folioman_client.core.fifo import InsufficientUnitsError, apply_fifo, net_units_from_transactions
from folioman_client.core.models import Holding as CoreHolding
from folioman_client.core.models import HoldingSource, Quote, SecurityType, TransactionType
from folioman_client.core.reconciliation import TOLERANCE, IntegrityStatus
from folioman_client.core.trading_calendar import last_trading_day, trading_days_between
from folioman_client.core.valuation import value_holdings
from folioman_client.core.xirr import cashflows_from_transactions, compute_xirr
from folioman_client.db import create_folioman_engine, create_sessionmaker
from folioman_client.db.models import (
    AppliedCorporateAction,
    CorporateActionReference,
    Family,
    Folio,
    Holding,
    Investor,
    InvestorValue,
    NAVHistory,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)

from folioman_client.services.mappers import to_core_security, to_core_transaction
from folioman_client.services.nav_service import NAVService
from folioman_client.services.projected_ledger import (
    compute_ledger,
    demerger_reductions,
    projected_transactions,
    security_key,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_BUY_TYPES = frozenset({TransactionType.BUY.value, TransactionType.TRANSFER_IN.value})
_SELL_TYPES = frozenset({TransactionType.SELL.value, TransactionType.TRANSFER_OUT.value})
_CA_INFLOW = frozenset(
    {TransactionType.BUY.value, TransactionType.BONUS.value, TransactionType.TRANSFER_IN.value}
)
_CA_OUTFLOW = frozenset({TransactionType.SELL.value, TransactionType.TRANSFER_OUT.value})
_NAV_STALE_GRACE_TRADING_DAYS = 1
_MAX_ATTEMPTS = 8
_MARKER_ID_BASE = 2_000_000_000

_SECURITY_TYPE_CATEGORY = {
    "equity": "Equity",
    "foreign_equity": "Equity",
    "bond": "Debt",
    "fd": "Debt",
}

_RETURN_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1M", 1),
    ("3M", 3),
    ("6M", 6),
    ("1Y", 12),
    ("3Y", 36),
    ("5Y", 60),
)


def _amc_label(security: Security) -> str:
    """Fund house for allocation breakdown."""
    if security.amc:
        return security.amc.name
    return (security.metadata_json or {}).get("amc") or ""


def _category_label(security: Security) -> str:
    """Equity vs Debt for allocation breakdown."""
    meta = security.metadata_json or {}

    equity_oriented = meta.get("equity_oriented")
    if equity_oriented is True:
        return "Equity"
    if equity_oriented is False:
        return "Debt"
    fund_type = (meta.get("fund_type") or "").strip()
    if fund_type:
        return fund_type.title()
    return _SECURITY_TYPE_CATEGORY.get(security.security_type, "Other")


def _trim(d: Decimal) -> str:
    """Format Decimal trimming trailing zeros."""
    text = f"{d:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _ratio_label(a: AppliedCorporateAction | None) -> str:
    """Human readable corporate action ratio."""
    if a is None:
        return ""
    if a.merger_ratio is not None:
        return f"{_trim(a.merger_ratio)} new per old"
    if a.bonus_ratio_a is not None and a.bonus_ratio_b is not None:
        return f"{a.bonus_ratio_a}:{a.bonus_ratio_b}"
    if a.unit_multiplier is not None:
        mult = a.unit_multiplier
        whole = mult == mult.to_integral_value()
        return f"1:{_trim(mult)}" if whole else f"{_trim(mult)}x"
    return ""


def _add_months(start: date, months: int) -> date:
    """Add months to a date, clamping day to month length."""
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _sample_dates(from_: date, to: date, granularity: str) -> list[date]:
    """Evenly-spaced sample dates ending on `to`."""
    if from_ > to:
        from_ = to
    out: list[date] = []
    cursor = from_
    if granularity == "daily":
        while cursor < to:
            out.append(cursor)
            cursor += timedelta(days=1)
    elif granularity == "weekly":
        while cursor < to:
            out.append(cursor)
            cursor += timedelta(days=7)
    else:  # monthly
        while cursor < to:
            out.append(cursor)
            cursor = _add_months(cursor, 1)
    out.append(to)
    return out


def _downsample(points: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
    """Downsample contiguous daily points to weekly or monthly."""
    if granularity == "daily" or not points:
        return points

    def period_key(d: date) -> tuple[int, int]:
        if granularity == "weekly":
            iso = d.isocalendar()
            return (iso[0], iso[1])
        return (d.year, d.month)

    last_per_period: dict[tuple[int, int], dict[str, Any]] = {}
    for point in points:
        last_per_period[period_key(point["date"])] = point
    return sorted(last_per_period.values(), key=lambda p: p["date"])


def _backoff(attempts: int) -> timedelta:
    return timedelta(minutes=min(2**attempts, 60))


class ValuationService:
    """Valuation & Performance Engine."""

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = session_factory or create_sessionmaker(self.engine)
        self._nav_service = NAVService(engine=self.engine)



    async def _current_positions(
        self, session: AsyncSession, investor_id: int
    ) -> list[tuple[Security, Decimal, date, str]]:
        """Yield (security, units, as_of_date, source) - current units per security.

        Units come per (security, folio) from transaction ledger when available,
        falling back to latest holding snapshot.
        """
        # 1. Projected transactions
        proj_txns = await projected_transactions(session, investor_id)
        txns_by_key: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for core in proj_txns:
            txns_by_key[(security_key(core.security), core.folio_number or "")].append(core)

        # 2. Holdings snapshots
        stmt_holdings = (
            select(Holding)
            .options(selectinload(Holding.security).selectinload(Security.amc), selectinload(Holding.folio))
            .where(Holding.investor_id == investor_id)
        )
        holdings = (await session.execute(stmt_holdings)).scalars().all()
        holdings_by_key: dict[tuple[str, str], list[Holding]] = defaultdict(list)
        sec_by_key: dict[str, Security] = {}
        for h in holdings:
            skey = security_key(h.security)
            holdings_by_key[(skey, h.folio.number if h.folio else "")].append(h)
            sec_by_key.setdefault(skey, h.security)

        # 3. Securities from transactions or merger counterparties
        stmt_cp = (
            select(AppliedCorporateAction.counterparty_security_id)
            .where(
                AppliedCorporateAction.investor_id == investor_id,
                AppliedCorporateAction.counterparty_security_id.is_not(None),
            )
        )
        cp_ids = [cid for cid in (await session.execute(stmt_cp)).scalars().all() if cid]

        stmt_sec = (
            select(Security)
            .options(selectinload(Security.amc))
            .where(
                (Security.transactions.any(Transaction.investor_id == investor_id))
                | (Security.id.in_(cp_ids))
            )
            .distinct()
        )
        for sec in (await session.execute(stmt_sec)).scalars().all():
            sec_by_key.setdefault(security_key(sec), sec)

        agg: dict[str, list[Any]] = {}
        all_keys = set(txns_by_key.keys()) | set(holdings_by_key.keys())
        for key in all_keys:
            skey = key[0]
            if key in txns_by_key:
                cores = txns_by_key[key]
                units = net_units_from_transactions(cores)
                security = sec_by_key.get(skey)
                as_of = max(c.date for c in cores)
                source = HoldingSource.LEDGER.value
            else:
                rows = holdings_by_key[key]
                latest = max(h.as_of_date for h in rows)
                units = sum((h.units for h in rows if h.as_of_date == latest), _ZERO)
                security = rows[0].security
                as_of = latest
                source = rows[0].source

            if security is None:
                continue

            slot = agg.setdefault(skey, [security, _ZERO, as_of, source])
            slot[0] = security
            slot[1] += units
            slot[2] = max(slot[2], as_of)
            if source == HoldingSource.LEDGER.value:
                slot[3] = source

        results: list[tuple[Security, Decimal, date, str]] = []
        for sec, units, as_of, source in agg.values():
            if units > _ZERO:
                results.append((sec, units, as_of, source))
        return results

    async def _value_investors(
        self, session: AsyncSession, investor_ids: list[int], as_of: date
    ) -> tuple[Any, dict[Any, tuple[int, str, str, str, str]]]:
        """Mark holdings to market using latest NAVHistory prices."""
        core_holdings: list[CoreHolding] = []
        price_by_sec_id: dict[int, Decimal] = {}
        meta_by_core: dict[Any, tuple[int, str, str, str, str]] = {}
        sec_ids: set[int] = set()

        all_positions: list[tuple[Security, Decimal, date, str]] = []
        for iid in investor_ids:
            positions = await self._current_positions(session, iid)
            all_positions.extend(positions)
            for sec, _, _, _ in positions:
                sec_ids.add(sec.id)

        # Batch load latest NAV on/before as_of for each security
        if sec_ids:
            stmt_nav = (
                select(NAVHistory.security_id, NAVHistory.nav)
                .where(NAVHistory.security_id.in_(sec_ids), NAVHistory.date <= as_of)
                .order_by(NAVHistory.security_id, NAVHistory.date.desc())
            )
            rows = (await session.execute(stmt_nav)).all()
            for sid, nav in rows:
                if sid not in price_by_sec_id:
                    price_by_sec_id[sid] = nav

        for sec, units, snap_date, source in all_positions:
            core_sec = to_core_security(sec)
            core_holdings.append(
                CoreHolding(
                    security=core_sec,
                    as_of_date=snap_date,
                    units=units,
                    source=HoldingSource(source),
                )
            )
            meta_by_core[core_sec] = (
                sec.id,
                sec.name,
                sec.security_type,
                _amc_label(sec),
                _category_label(sec),
            )

        def nav_provider(security: Any, _as_of: date) -> Decimal | None:
            # Match by ISIN, symbol, name
            for sid, nav in price_by_sec_id.items():
                meta = meta_by_core.get(security)
                if meta and meta[0] == sid:
                    return nav
            return None

        def quote_provider(security: Any, _as_of: date) -> Quote | None:
            price = nav_provider(security, _as_of)
            if price is None:
                return None
            return Quote(as_of=_as_of, price=price, currency=security.currency, source="navhistory")

        val = value_holdings(
            core_holdings,
            as_of=as_of,
            nav_provider=nav_provider,
            quote_provider=quote_provider,
            crypto_provider=quote_provider,
        )
        return val, meta_by_core

    async def _ledger_index(
        self, session: AsyncSession, investor_ids: list[int]
    ) -> tuple[dict[tuple[int, int | None], dict[str, Any]], dict[tuple[int, int | None], dict[str, Any]]]:
        """Group ledger transactions and holdings by (security_id, folio_id)."""
        stmt_cp = (
            select(AppliedCorporateAction.counterparty_security_id)
            .where(
                AppliedCorporateAction.investor_id.in_(investor_ids),
                AppliedCorporateAction.counterparty_security_id.is_not(None),
            )
        )
        cp_ids = [cid for cid in (await session.execute(stmt_cp)).scalars().all() if cid]

        stmt_sec = (
            select(Security)
            .options(selectinload(Security.amc))
            .where(
                (Security.transactions.any(Transaction.investor_id.in_(investor_ids)))
                | (Security.id.in_(cp_ids))
            )
            .distinct()
        )
        sec_by_key: dict[str, Security] = {}
        for sec in (await session.execute(stmt_sec)).scalars().all():
            sec_by_key.setdefault(security_key(sec), sec)

        txn_keys: dict[tuple[int, int | None], dict[str, Any]] = {}
        for iid in investor_ids:
            stmt_folios = select(Folio).where(Folio.investor_id == iid)
            folios = (await session.execute(stmt_folios)).scalars().all()
            folio_by_num = {f.number: f.id for f in folios}

            for core in await projected_transactions(session, iid):
                sec = sec_by_key.get(security_key(core.security))
                if sec is None:
                    continue
                key = (sec.id, folio_by_num.get(core.folio_number or ""))
                rec = txn_keys.setdefault(key, {"security": sec, "core": [], "cash": []})
                rec["core"].append((core.date, core))
                amount = core.amount if core.amount is not None else (core.units * core.nav_or_price)
                rec["cash"].append((core.date, core.type.value, amount))

        hold_keys: dict[tuple[int, int | None], dict[str, Any]] = {}
        stmt_holds = (
            select(Holding)
            .options(selectinload(Holding.security), selectinload(Holding.folio))
            .where(Holding.investor_id.in_(investor_ids))
        )
        for h in (await session.execute(stmt_holds)).scalars().all():
            key = (h.security_id, h.folio_id)
            rec = hold_keys.setdefault(key, {"security": h.security, "rows": []})
            rec["rows"].append(h)

        return txn_keys, hold_keys

    async def _nav_index(
        self, session: AsyncSession, security_ids: Sequence[int], upto: date
    ) -> dict[int, list[tuple[date, Decimal]]]:
        """Ascending [(date, nav)] up to `upto` for each security."""
        idx: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
        if not security_ids:
            return idx
        stmt = (
            select(NAVHistory.security_id, NAVHistory.date, NAVHistory.nav)
            .where(NAVHistory.security_id.in_(list(security_ids)), NAVHistory.date <= upto)
            .order_by(NAVHistory.security_id, NAVHistory.date)
        )
        for sid, d, nav in (await session.execute(stmt)).all():
            idx[sid].append((d, nav))
        return idx

    def _price_at(self, nav_idx: dict[int, list[tuple[date, Decimal]]], sec_id: int, as_of: date) -> Decimal | None:
        seq = nav_idx.get(sec_id)
        if not seq:
            return None
        lo, hi = 0, len(seq)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[mid][0] <= as_of:
                lo = mid + 1
            else:
                hi = mid
        return seq[lo - 1][1] if lo > 0 else None

    def _positions_asof(
        self,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]],
        hold_keys: dict[tuple[int, int | None], dict[str, Any]],
        as_of: date,
        reductions: dict[str, list[Any]] | None = None,
    ) -> dict[int, list[Any]]:
        reductions = reductions or {}
        agg: dict[int, list[Any]] = {}

        for (sec_id, _fid), rec in txn_keys.items():
            cores = [core for (txn_date, core) in rec["core"] if txn_date <= as_of]
            if not cores:
                continue
            sec = rec["security"]
            ident = sec.isin or sec.symbol or sec.name
            sec_reductions = [(ex, by) for (ex, by) in reductions.get(ident, []) if ex <= as_of]
            try:
                fifo = apply_fifo(cores, demerger_reductions=sec_reductions)
                units, invested = fifo.balance, fifo.invested
            except InsufficientUnitsError:
                units, invested = net_units_from_transactions(cores), _ZERO

            slot = agg.setdefault(sec_id, [rec["security"], _ZERO, _ZERO])
            slot[1] += units
            slot[2] += invested

        for (sec_id, fid), rec in hold_keys.items():
            if (sec_id, fid) in txn_keys:
                continue
            rows = [h for h in rec["rows"] if h.as_of_date <= as_of]
            if not rows:
                continue
            latest = max(h.as_of_date for h in rows)
            current = [h for h in rows if h.as_of_date == latest]
            units = sum((h.units for h in current), _ZERO)
            invested = sum(
                (h.avg_cost_observed * h.units for h in current if h.avg_cost_observed is not None),
                _ZERO,
            )
            slot = agg.setdefault(sec_id, [rec["security"], _ZERO, _ZERO])
            slot[1] += units
            slot[2] += invested

        return agg

    def _security_cashflows(
        self, txn_keys: dict[tuple[int, int | None], dict[str, Any]]
    ) -> dict[int, list[tuple[date, Decimal]]]:
        by_sec: dict[int, list[tuple[date, Decimal]]] = defaultdict(list)
        for (sec_id, _fid), rec in txn_keys.items():
            for txn_date, ttype, cash in rec["cash"]:
                if ttype in _BUY_TYPES:
                    by_sec[sec_id].append((txn_date, cash))
                elif ttype in _SELL_TYPES:
                    by_sec[sec_id].append((txn_date, -cash))
                elif ttype == TransactionType.DIVIDEND.value and cash:
                    by_sec[sec_id].append((txn_date, -cash))
        return by_sec

    async def _holding_extras(
        self,
        session: AsyncSession,
        investor_ids: list[int],
        as_of: date,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]] | None = None,
        hold_keys: dict[tuple[int, int | None], dict[str, Any]] | None = None,
    ) -> dict[int, dict[str, Any]]:
        if txn_keys is None or hold_keys is None:
            txn_keys, hold_keys = await self._ledger_index(session, investor_ids)

        merged_reductions: dict[str, list[Any]] = {}
        for iid in investor_ids:
            for ident, events in (await demerger_reductions(session, iid)).items():
                merged_reductions.setdefault(ident, []).extend(events)

        positions = self._positions_asof(txn_keys, hold_keys, as_of, merged_reductions)
        nav_idx = await self._nav_index(session, list(positions.keys()), as_of)
        cash_by_sec = self._security_cashflows(txn_keys)

        extras: dict[int, dict[str, Any]] = {}
        for sec_id, (_sec, units, invested) in positions.items():
            seq = nav_idx.get(sec_id) or []
            latest = seq[-1][1] if seq else None
            prev = seq[-2][1] if len(seq) >= 2 else None
            day_change_inr = day_change_pct = None
            if units > _ZERO and latest is not None and prev is not None and prev != _ZERO:
                day_change_inr = units * (latest - prev)
                day_change_pct = float((latest - prev) / prev)

            flows = cash_by_sec.get(sec_id)
            xirr = None
            if flows:
                terminal = (units * latest if latest is not None else None) if units > _ZERO else _ZERO
                if terminal is not None:
                    cashflows = cashflows_from_transactions(
                        flows, present_date=as_of, present_value=terminal
                    )
                    xirr = compute_xirr(cashflows)

            extras[sec_id] = {
                "invested_inr": invested,
                "latest_nav": latest,
                "day_change_inr": day_change_inr,
                "day_change_pct": day_change_pct,
                "xirr": xirr,
            }
        return extras

    def _day_change_total(self, extras: dict[int, dict[str, Any]]) -> Decimal | None:
        contribs = [e["day_change_inr"] for e in extras.values() if e["day_change_inr"] is not None]
        return sum(contribs, _ZERO) if contribs else None

    def _rollup(
        self,
        valuation: Any,
        meta_by_security: dict[Any, tuple[int, str, str, str, str]],
        extras: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        extras = extras or {}
        asset_mix: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        amc_mix: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        category_mix: dict[str, Decimal] = defaultdict(lambda: _ZERO)
        top_holdings: list[dict[str, Any]] = []

        for row in valuation.rows:
            sec_id, name, sec_type, amc_name, category = meta_by_security[row.security]
            if row.value_inr is not None:
                asset_mix[sec_type] += row.value_inr
                amc_mix[amc_name or "Other"] += row.value_inr
                category_mix[category or "Other"] += row.value_inr
            extra = extras.get(sec_id, {})
            invested = extra.get("invested_inr")
            return_pct = None
            if row.value_inr is not None and invested not in (None, _ZERO):
                return_pct = float((row.value_inr - invested) / invested)

            top_holdings.append(
                {
                    "security_id": sec_id,
                    "name": name,
                    "security_type": sec_type,
                    "symbol": row.security.symbol,
                    "amc": amc_name or "Other",
                    "category": category or "Other",
                    "units": row.units,
                    "value_inr": row.value_inr,
                    "invested_inr": invested,
                    "latest_nav": extra.get("latest_nav"),
                    "return_pct": return_pct,
                    "xirr": extra.get("xirr"),
                    "day_change_inr": extra.get("day_change_inr"),
                    "day_change_pct": extra.get("day_change_pct"),
                }
            )

        top_holdings.sort(key=lambda r: r["value_inr"] or _ZERO, reverse=True)

        def _buckets(mix: dict[str, Decimal]) -> list[dict[str, Any]]:
            return [
                {"label": label, "value_inr": val}
                for label, val in sorted(mix.items(), key=lambda kv: kv[1], reverse=True)
            ]

        return {
            "total_inr": valuation.total_inr,
            "asset_mix": [
                {"security_type": stype, "value_inr": val} for stype, val in asset_mix.items()
            ],
            "amc_mix": _buckets(amc_mix),
            "category_mix": _buckets(category_mix),
            "top_holdings": top_holdings[:10],
            "holdings": top_holdings,
            "stale_count": len(valuation.stale_rows),
            "holdings_count": len(valuation.rows),
        }

    async def _book_navs_as_of(self, session: AsyncSession, investor_ids: Sequence[int], as_of: date) -> date | None:
        stmt_sec = (
            select(Transaction.security_id)
            .where(Transaction.investor_id.in_(investor_ids))
            .union(select(Holding.security_id).where(Holding.investor_id.in_(investor_ids)))
        )
        sec_ids = [sid for sid in (await session.execute(stmt_sec)).scalars().all() if sid]
        if not sec_ids:
            return None
        stmt_nav = select(func.max(NAVHistory.date)).where(
            NAVHistory.security_id.in_(sec_ids), NAVHistory.date <= as_of
        )
        return await session.scalar(stmt_nav)

    def _navs_stale(self, navs_as_of: date | None, as_of: date) -> bool:
        if navs_as_of is None:
            return False
        behind = trading_days_between(navs_as_of, last_trading_day(as_of))
        return behind > _NAV_STALE_GRACE_TRADING_DAYS

    def _compute_xirr(
        self,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]],
        nav_idx: dict[int, list[tuple[date, Decimal]]],
        as_of: date,
    ) -> float | None:
        flows: list[tuple[date, Decimal]] = []
        for rec in txn_keys.values():
            for txn_date, ttype, cash in rec["cash"]:
                if ttype in _BUY_TYPES:
                    flows.append((txn_date, cash))
                elif ttype in _SELL_TYPES:
                    flows.append((txn_date, -cash))
                elif ttype == TransactionType.DIVIDEND.value and cash:
                    flows.append((txn_date, -cash))
        if not flows:
            return None

        terminal = _ZERO
        for sec_id, (_sec, units, _inv) in self._positions_asof(txn_keys, {}, as_of).items():
            if units <= _ZERO:
                continue
            price = self._price_at(nav_idx, sec_id, as_of)
            if price is not None:
                terminal += units * price

        cashflows = cashflows_from_transactions(flows, present_date=as_of, present_value=terminal)
        return compute_xirr(cashflows)

    def _value_at(
        self,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]],
        nav_idx: dict[int, list[tuple[date, Decimal]]],
        when: date,
    ) -> Decimal:
        total = _ZERO
        for sec_id, (_sec, units, _inv) in self._positions_asof(txn_keys, {}, when).items():
            if units <= _ZERO:
                continue
            price = self._price_at(nav_idx, sec_id, when)
            if price is not None:
                total += units * price
        return total

    def _windowed_xirr(
        self,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]],
        nav_idx: dict[int, list[tuple[date, Decimal]]],
        start: date,
        as_of: date,
        terminal: Decimal,
    ) -> float | None:
        flows: list[tuple[date, Decimal]] = []
        opening = self._value_at(txn_keys, nav_idx, start)
        if opening > _ZERO:
            flows.append((start, opening))
        for rec in txn_keys.values():
            for txn_date, ttype, cash in rec["cash"]:
                if not (start < txn_date <= as_of):
                    continue
                if ttype in _BUY_TYPES:
                    flows.append((txn_date, cash))
                elif ttype in _SELL_TYPES:
                    flows.append((txn_date, -cash))
                elif ttype == TransactionType.DIVIDEND.value and cash:
                    flows.append((txn_date, -cash))
        if not flows:
            return None
        cashflows = cashflows_from_transactions(flows, present_date=as_of, present_value=terminal)
        return compute_xirr(cashflows)

    def _period_return(self, label: str, start: date, as_of: date, rate: float) -> dict[str, Any]:
        days = (as_of - start).days
        base = 1.0 + rate
        absolute = base ** (days / 365.0) - 1.0 if base > 0.0 else None
        return {"period": label, "annualized": rate, "absolute": absolute, "days": days}

    def _compute_period_returns(
        self,
        txn_keys: dict[tuple[int, int | None], dict[str, Any]],
        nav_idx: dict[int, list[tuple[date, Decimal]]],
        as_of: date,
    ) -> list[dict[str, Any]]:
        if not txn_keys:
            return []
        dates = [txn_date for rec in txn_keys.values() for (txn_date, _t, _c) in rec["cash"]]
        if not dates:
            return []
        inception = min(dates)
        terminal = self._value_at(txn_keys, nav_idx, as_of)

        out: list[dict[str, Any]] = []
        for label, months in _RETURN_WINDOWS:
            start = _add_months(as_of, -months)
            if start < inception:
                continue
            rate = self._windowed_xirr(txn_keys, nav_idx, start, as_of, terminal)
            if rate is not None:
                out.append(self._period_return(label, start, as_of, rate))

        all_rate = self._windowed_xirr(txn_keys, nav_idx, inception - timedelta(days=1), as_of, terminal)
        if all_rate is not None:
            out.append(self._period_return("All", inception, as_of, all_rate))
        return out

    async def build_investor_summary(
        self, investor_id: int, as_of: date | None = None
    ) -> dict[str, Any]:
        """Per-investor headline numbers: valuation, allocations, XIRR, period returns."""
        as_of_date = as_of or date.today()
        async with self.session_factory() as session:
            stmt_inv = select(Investor).where(Investor.id == investor_id)
            investor = (await session.execute(stmt_inv)).scalar_one_or_none()
            if investor is None:
                raise ValueError(f"Investor {investor_id} not found")

            valuation, meta_by_sec = await self._value_investors(session, [investor_id], as_of_date)
            txn_keys, hold_keys = await self._ledger_index(session, [investor_id])
            extras = await self._holding_extras(session, [investor_id], as_of_date, txn_keys, hold_keys)
            rollup = self._rollup(valuation, meta_by_sec, extras)

            sec_ids = {k[0] for k in txn_keys}
            nav_idx = await self._nav_index(session, list(sec_ids), as_of_date)
            xirr = self._compute_xirr(txn_keys, nav_idx, as_of_date)
            period_returns = self._compute_period_returns(txn_keys, nav_idx, as_of_date)

            unpriced_fund_count = sum(
                1
                for row in valuation.stale_rows
                if meta_by_sec.get(row.security, (None,) * 5)[2] == SecurityType.MF.value
            )

            stmt_statuses = select(SecurityIntegrityStatus).where(
                SecurityIntegrityStatus.investor_id == investor_id
            )
            statuses = (await session.execute(stmt_statuses)).scalars().all()
            integrity_unit_count = len(statuses)
            tax_ready_count = sum(1 for s in statuses if s.tax_safe)
            needs_attention_count = sum(1 for s in statuses if s.status == IntegrityStatus.MISMATCH.value)
            snapshot_count = sum(1 for s in statuses if s.status == IntegrityStatus.SNAPSHOT_ONLY.value)

            total_inr = rollup["total_inr"]
            summary_as_of = as_of_date
            is_provisional = False
            if total_inr == _ZERO and rollup["holdings_count"] > 0:
                stmt_last_val = (
                    select(InvestorValue)
                    .where(InvestorValue.investor_id == investor_id, InvestorValue.date <= as_of_date)
                    .order_by(InvestorValue.date.desc())
                )
                last_known = (await session.execute(stmt_last_val)).scalars().first()
                if last_known is not None:
                    total_inr = last_known.value_inr
                    summary_as_of = last_known.date
                    is_provisional = True

            navs_as_of = await self._book_navs_as_of(session, [investor_id], as_of_date)
            day_change = self._day_change_total(extras)

            return {
                "investor_id": investor.id,
                "as_of": summary_as_of,
                "total_inr": total_inr,
                "is_provisional": is_provisional,
                "navs_as_of": navs_as_of,
                "navs_stale": self._navs_stale(navs_as_of, as_of_date),
                "holdings_count": rollup["holdings_count"],
                "integrity_unit_count": integrity_unit_count,
                "tax_ready_count": tax_ready_count,
                "needs_attention_count": needs_attention_count,
                "snapshot_count": snapshot_count,
                "stale_count": rollup["stale_count"],
                "unpriced_fund_count": unpriced_fund_count,
                "last_import_at": None,
                "day_change_inr": day_change,
                "xirr": xirr,
                "period_returns": period_returns,
                "asset_mix": rollup["asset_mix"],
                "amc_mix": rollup["amc_mix"],
                "category_mix": rollup["category_mix"],
                "top_holdings": rollup["top_holdings"],
                "holdings": rollup["holdings"],
            }

    async def build_family_summary(
        self, family_id: int, as_of: date | None = None
    ) -> dict[str, Any]:
        """Aggregate valuation across all family members."""
        as_of_date = as_of or date.today()
        async with self.session_factory() as session:
            stmt_fam = select(Family).where(Family.id == family_id)
            family = (await session.execute(stmt_fam)).scalar_one_or_none()
            if family is None:
                raise ValueError(f"Family {family_id} not found")

            stmt_invs = select(Investor.id).where(Investor.family_id == family_id)
            investor_ids = list((await session.execute(stmt_invs)).scalars().all())
            if not investor_ids:
                return {
                    "family_id": family_id,
                    "as_of": as_of_date,
                    "investor_count": 0,
                    "folio_count": 0,
                    "total_inr": _ZERO,
                    "asset_mix": [],
                    "top_holdings": [],
                    "stale_count": 0,
                    "integrity_unit_count": 0,
                    "tax_ready_count": 0,
                    "needs_attention_count": 0,
                    "navs_as_of": None,
                    "navs_stale": False,
                    "day_change_inr": None,
                    "xirr": None,
                    "period_returns": [],
                }

            valuation, meta_by_sec = await self._value_investors(session, investor_ids, as_of_date)
            txn_keys, hold_keys = await self._ledger_index(session, investor_ids)
            extras = await self._holding_extras(session, investor_ids, as_of_date, txn_keys, hold_keys)
            rollup = self._rollup(valuation, meta_by_sec, extras)

            sec_ids = {k[0] for k in txn_keys}
            nav_idx = await self._nav_index(session, list(sec_ids), as_of_date)
            xirr = self._compute_xirr(txn_keys, nav_idx, as_of_date)
            period_returns = self._compute_period_returns(txn_keys, nav_idx, as_of_date)

            stmt_statuses = select(SecurityIntegrityStatus).where(
                SecurityIntegrityStatus.investor_id.in_(investor_ids)
            )
            statuses = (await session.execute(stmt_statuses)).scalars().all()
            navs_as_of = await self._book_navs_as_of(session, investor_ids, as_of_date)
            stmt_folios = select(func.count(Folio.id)).where(Folio.investor_id.in_(investor_ids))
            folio_count = (await session.scalar(stmt_folios)) or 0

            return {
                "family_id": family.id,
                "as_of": as_of_date,
                "investor_count": len(investor_ids),
                "folio_count": folio_count,
                "total_inr": rollup["total_inr"],
                "asset_mix": rollup["asset_mix"],
                "top_holdings": rollup["top_holdings"],
                "stale_count": rollup["stale_count"],
                "integrity_unit_count": len(statuses),
                "tax_ready_count": sum(1 for s in statuses if s.tax_safe),
                "needs_attention_count": sum(1 for s in statuses if s.status == IntegrityStatus.MISMATCH.value),
                "navs_as_of": navs_as_of,
                "navs_stale": self._navs_stale(navs_as_of, as_of_date),
                "day_change_inr": self._day_change_total(extras),
                "xirr": xirr,
                "period_returns": period_returns,
            }

    async def _scheme_ledger(
        self, session: AsyncSession, investor_id: int, security: Security, as_of: date
    ) -> tuple[list[dict[str, Any]], list[Any], date | None]:
        projected = await compute_ledger(session, investor_id, security.id, as_of=as_of)

        real_ids = [c.ledger_id for c in projected if c.ledger_id is not None]
        origin_sec: dict[int, int] = {}
        if real_ids:
            stmt_origin = select(Transaction.id, Transaction.security_id).where(Transaction.id.in_(real_ids))
            origin_sec = dict((await session.execute(stmt_origin)).all())

        receipts: dict[int, Decimal] = defaultdict(lambda: _ZERO)
        for c in projected:
            if c.ledger_id is None:
                continue
            osec = origin_sec.get(c.ledger_id)
            if osec is None or osec == security.id:
                continue
            if c.type.value in _CA_INFLOW:
                receipts[osec] += c.units
            elif c.type.value in _CA_OUTFLOW:
                receipts[osec] -= c.units

        stmt_raw_txns = (
            select(Transaction)
            .options(selectinload(Transaction.folio))
            .where(Transaction.investor_id == investor_id, Transaction.security_id == security.id)
            .order_by(Transaction.date, Transaction.id)
        )
        raw_txns = (await session.execute(stmt_raw_txns)).scalars().all()

        stmt_ca_merger = (
            select(AppliedCorporateAction)
            .options(selectinload(AppliedCorporateAction.security))
            .where(
                AppliedCorporateAction.investor_id == investor_id,
                AppliedCorporateAction.counterparty_security_id == security.id,
                AppliedCorporateAction.kind == "merger",
            )
        )
        ca_mergers = (await session.execute(stmt_ca_merger)).scalars().all()

        stmt_ca_scale = (
            select(AppliedCorporateAction)
            .where(
                AppliedCorporateAction.investor_id == investor_id,
                AppliedCorporateAction.security_id == security.id,
                AppliedCorporateAction.kind.in_(["split", "bonus"]),
            )
        )
        ca_scales = (await session.execute(stmt_ca_scale)).scalars().all()

        trade, merger, scale = 0, 1, 2
        timeline: list[tuple[date, int, int, str, Any]] = []
        seq = 0
        for t in raw_txns:
            timeline.append((t.date, trade, seq, "trade", t))
            seq += 1
        for a in ca_mergers:
            timeline.append((a.ex_date, merger, seq, "merger", a))
            seq += 1
        for a in ca_scales:
            timeline.append((a.ex_date, scale, seq, "scale", a))
            seq += 1
        timeline.sort(key=lambda e: (e[0], e[1], e[2]))

        rows: list[dict[str, Any]] = []
        marker_seq = 0
        balance = _ZERO
        partial_from: date | None = None
        for _when, _order, _seq, kind, obj in timeline:
            if kind == "trade":
                complete = obj.cost_basis_complete
                signed = (
                    obj.units
                    if obj.transaction_type in _CA_INFLOW
                    else -obj.units
                    if obj.transaction_type in _CA_OUTFLOW
                    else _ZERO
                )
                if complete:
                    balance += signed
                    row_balance = balance
                else:
                    row_balance = None
                    if partial_from is None:
                        partial_from = obj.date
                rows.append(
                    {
                        "id": obj.id,
                        "investor_id": investor_id,
                        "security_id": security.id,
                        "folio_id": obj.folio_id,
                        "date": obj.date,
                        "transaction_type": obj.transaction_type,
                        "units": obj.units,
                        "nav_or_price": obj.nav_or_price,
                        "amount": obj.amount,
                        "fees": obj.fees,
                        "stamp_duty": obj.stamp_duty,
                        "brokerage": obj.brokerage,
                        "currency": obj.currency,
                        "source": obj.source,
                        "narration": obj.narration,
                        "cost_basis_complete": complete,
                        "via_security": None,
                        "balance": row_balance,
                    }
                )
                continue

            if kind == "merger":
                added = receipts.get(obj.security_id, _ZERO)
                txn_type = "merger"
                via = obj.security.symbol or obj.security.name
            else:
                added = balance * ((obj.unit_multiplier or _ONE) - _ONE)
                txn_type = obj.kind
                via = None
            ratio = _ratio_label(obj)
            balance += added
            marker_seq += 1
            rows.append(
                {
                    "id": _MARKER_ID_BASE + marker_seq,
                    "investor_id": investor_id,
                    "security_id": security.id,
                    "folio_id": None,
                    "date": obj.ex_date,
                    "transaction_type": txn_type,
                    "units": added,
                    "nav_or_price": _ZERO,
                    "amount": None,
                    "fees": _ZERO,
                    "stamp_duty": _ZERO,
                    "brokerage": _ZERO,
                    "currency": "INR",
                    "source": "corporate-action",
                    "narration": ratio,
                    "cost_basis_complete": True,
                    "via_security": via,
                    "balance": balance,
                }
            )
        return rows, projected, partial_from

    async def _folio_balances(
        self, session: AsyncSession, investor_id: int, security: Security, txns: Sequence[Transaction], price: Decimal | None, as_of: date
    ) -> list[dict[str, Any]]:
        units_by_folio: dict[int, Decimal] = {}
        meta: dict[int, Folio] = {}

        grouped: dict[int, list[Transaction]] = {}
        for t in txns:
            if t.folio_id is None:
                continue
            grouped.setdefault(t.folio_id, []).append(t)
            if t.folio:
                meta[t.folio_id] = t.folio
        for fid, group in grouped.items():
            units_by_folio[fid] = net_units_from_transactions([to_core_transaction(t) for t in group])

        stmt_h = (
            select(Holding)
            .options(selectinload(Holding.folio))
            .where(
                Holding.investor_id == investor_id,
                Holding.security_id == security.id,
                Holding.as_of_date <= as_of,
            )
        )
        latest_date: dict[int, date] = {}
        for h in (await session.execute(stmt_h)).scalars().all():
            if h.folio_id is None or h.folio_id in grouped:
                continue
            if h.folio:
                meta.setdefault(h.folio_id, h.folio)
            prev = latest_date.get(h.folio_id)
            if prev is None or h.as_of_date > prev:
                latest_date[h.folio_id] = h.as_of_date
                units_by_folio[h.folio_id] = h.units
            elif h.as_of_date == prev:
                units_by_folio[h.folio_id] += h.units

        rows: list[dict[str, Any]] = []
        for fid, folio in meta.items():
            units = units_by_folio.get(fid, _ZERO)
            if units == _ZERO:
                continue
            rows.append(
                {
                    "number": folio.number,
                    "broker": folio.broker,
                    "folio_type": folio.folio_type,
                    "units": units,
                    "value_inr": (units * price) if price is not None else None,
                }
            )
        rows.sort(key=lambda r: r["units"], reverse=True)
        return rows

    async def _holdings_anchor(
        self, session: AsyncSession, investor_id: int, security_id: int, as_of: date
    ) -> Decimal | None:
        stmt = select(Holding).where(
            Holding.investor_id == investor_id,
            Holding.security_id == security_id,
            Holding.as_of_date <= as_of,
        )
        latest: dict[int | None, tuple[date, Decimal]] = {}
        for h in (await session.execute(stmt)).scalars().all():
            cur = latest.get(h.folio_id)
            if cur is None or h.as_of_date > cur[0]:
                latest[h.folio_id] = (h.as_of_date, h.units)
            elif h.as_of_date == cur[0]:
                latest[h.folio_id] = (cur[0], cur[1] + h.units)
        if not latest:
            return None
        return sum((u for (_d, u) in latest.values()), _ZERO)

    async def _build_equity_dividend_detail(
        self,
        session: AsyncSession,
        investor_id: int,
        security: Security,
        as_of: date,
        current_units: Decimal,
        invested_inr: Decimal | None,
    ) -> dict[str, Any]:
        """Dividend detail for equity scheme view."""
        if security.security_type != SecurityType.EQUITY.value:
            return {"dividends": [], "dividends_received_inr": None, "dividend_yield_on_cost": None}

        stmt_refs = select(CorporateActionReference).where(
            CorporateActionReference.parsed_type == "dividend",
            CorporateActionReference.needs_review.is_(False),
            CorporateActionReference.amount.is_not(None),
        )
        if security.isin:
            stmt_refs = stmt_refs.where(CorporateActionReference.isin == security.isin)
        elif security.symbol:
            stmt_refs = stmt_refs.where(CorporateActionReference.symbol == security.symbol.upper())
        else:
            return {"dividends": [], "dividends_received_inr": None, "dividend_yield_on_cost": None}

        schedule_refs = (await session.execute(stmt_refs.order_by(CorporateActionReference.ex_date.desc()))).scalars().all()

        stmt_txns = select(Transaction).where(
            Transaction.investor_id == investor_id, Transaction.security_id == security.id
        )
        ledger_orm_txns = (await session.execute(stmt_txns)).scalars().all()
        has_ledger = bool(ledger_orm_txns)

        attributed_amounts: dict[int, Decimal] = {}
        for txn in ledger_orm_txns:
            if txn.transaction_type != TransactionType.DIVIDEND.value:
                continue
            ref = txn.source_ref or ""
            if not ref.startswith("dividend:ca-ref:"):
                continue
            try:
                ref_id = int(ref.removeprefix("dividend:ca-ref:"))
                attributed_amounts[ref_id] = attributed_amounts.get(ref_id, _ZERO) + (txn.amount or _ZERO)
            except ValueError:
                continue

        core_sec = to_core_security(security)
        ledger_cores = await compute_ledger(session, investor_id, security.id)
        folio_ids = {t.folio_id for t in ledger_orm_txns if t.folio_id}
        stmt_folios = select(Folio).where(Folio.id.in_(list(folio_ids))) if folio_ids else None
        folios_by_id = {f.id: f for f in (await session.execute(stmt_folios)).scalars().all()} if stmt_folios is not None else {}

        rows: list[dict[str, Any]] = []
        for ref in schedule_refs:
            row: dict[str, Any] = {
                "reference_id": ref.id,
                "ex_date": ref.ex_date,
                "record_date": ref.record_date,
                "dividend_per_share": ref.amount,
                "units": None,
                "amount_inr": None,
                "kind": "schedule",
            }
            if has_ledger and ref.ex_date <= as_of:
                units = _ZERO
                for fid in folio_ids:
                    folio = folios_by_id.get(fid)
                    if folio is None:
                        continue
                    held = held_units_asof(
                        ledger_cores,
                        core_sec,
                        ref.ex_date,
                        folio_number=folio.number or "",
                    )
                    units += held
                if units > _ZERO:
                    row["units"] = units
                    if ref.id in attributed_amounts:
                        row["amount_inr"] = attributed_amounts[ref.id]
                        row["kind"] = "attributed"
                    else:
                        row["amount_inr"] = units * ref.amount
                        row["kind"] = "computed"
            elif not has_ledger:
                if ref.ex_date > as_of and current_units > _ZERO:
                    row["units"] = current_units
                    row["amount_inr"] = current_units * ref.amount
                    row["kind"] = "estimate"
            rows.append(row)

        received = sum(
            (row["amount_inr"] or _ZERO for row in rows if row["kind"] in ("attributed", "computed")),
            _ZERO,
        )
        received_out = received if has_ledger and received > _ZERO else None
        yield_on_cost = None
        if received_out is not None and invested_inr not in (None, _ZERO):
            yield_on_cost = float(received_out / invested_inr)

        return {
            "dividends": rows,
            "dividends_received_inr": received_out,
            "dividend_yield_on_cost": yield_on_cost,
        }

    async def build_scheme_detail(
        self, investor_id: int, security_id: int, as_of: date | None = None
    ) -> dict[str, Any]:
        """Per-(investor, security) detail view."""
        as_of_date = as_of or date.today()
        async with self.session_factory() as session:
            stmt_sec = (
                select(Security)
                .options(selectinload(Security.amc))
                .where(Security.id == security_id)
            )
            security = (await session.execute(stmt_sec)).scalar_one_or_none()
            if security is None:
                raise ValueError(f"Security {security_id} not found")

            txn_keys, hold_keys = await self._ledger_index(session, [investor_id])
            positions = self._positions_asof(txn_keys, hold_keys, as_of_date)
            extras = await self._holding_extras(session, [investor_id], as_of_date, txn_keys, hold_keys)

            pos = positions.get(security.id)
            units = pos[1] if pos else _ZERO
            ex = extras.get(security.id, {})
            invested = ex.get("invested_inr")

            stmt_latest = (
                select(NAVHistory.date, NAVHistory.nav)
                .where(NAVHistory.security_id == security.id, NAVHistory.date <= as_of_date)
                .order_by(NAVHistory.date.desc())
            )
            latest_row = (await session.execute(stmt_latest)).first()
            latest_nav_date, latest_nav = latest_row if latest_row else (None, None)

            price = latest_nav
            if units <= _ZERO:
                value = _ZERO
            elif price is not None:
                value = units * price
            else:
                value = None

            return_pct = None
            if value is not None and invested not in (None, _ZERO):
                return_pct = float((value - invested) / invested)

            txns, complete_core, partial_from = await self._scheme_ledger(session, investor_id, security, as_of_date)

            stmt_cb_txns = (
                select(Transaction)
                .options(selectinload(Transaction.folio))
                .where(
                    Transaction.investor_id == investor_id,
                    Transaction.security_id == security.id,
                    Transaction.cost_basis_complete.is_(True),
                )
            )
            cb_txns = (await session.execute(stmt_cb_txns)).scalars().all()
            folios = await self._folio_balances(session, investor_id, security, cb_txns, price, as_of_date)

            anchor = await self._holdings_anchor(session, investor_id, security.id, as_of_date)
            has_incomplete = partial_from is not None
            complete_net = net_units_from_transactions(complete_core)
            if anchor is not None:
                partial_history = has_incomplete and abs(complete_net - anchor) > TOLERANCE
            else:
                partial_history = has_incomplete

            xirr = ex.get("xirr")
            if not complete_core:
                xirr_status = "estimated"
            elif xirr is None:
                xirr_status = "estimated"
            elif (as_of_date - min(c.date for c in complete_core)).days < 365:
                xirr_status = "less_than_1_year"
            else:
                xirr_status = "valid"

            stmt_statuses = (
                select(SecurityIntegrityStatus)
                .options(selectinload(SecurityIntegrityStatus.security), selectinload(SecurityIntegrityStatus.folio))
                .where(
                    SecurityIntegrityStatus.investor_id == investor_id,
                    SecurityIntegrityStatus.security_id == security.id,
                )
            )
            integrity_rows = (await session.execute(stmt_statuses)).scalars().all()

            stmt_navs = (
                select(NAVHistory.date, NAVHistory.nav)
                .where(NAVHistory.security_id == security.id, NAVHistory.date <= as_of_date)
                .order_by(NAVHistory.date)
            )
            nav_history = [{"date": d, "nav": n} for d, n in (await session.execute(stmt_navs)).all()]

            dividend_detail = await self._build_equity_dividend_detail(
                session, investor_id, security, as_of_date, units, invested
            )

            corporate_actions = [
                {
                    "ex_date": r["date"],
                    "kind": r["transaction_type"],
                    "ratio": r["narration"],
                    "counterparty": r["via_security"],
                    "units_added": r["units"] if r["units"] > _ZERO else None,
                    "units_after": r["balance"],
                }
                for r in txns
                if r["source"] == "corporate-action"
            ]

            return {
                "security": {
                    "id": security.id,
                    "name": security.name,
                    "isin": security.isin,
                    "symbol": security.symbol,
                    "security_type": security.security_type,
                    "amfi_code": security.amfi_code,
                    "amc": security.amc.name if security.amc else None,
                    "category": (security.metadata_json or {}).get("category"),
                },

                "as_of": as_of_date,
                "units": units,
                "value_inr": value,
                "invested_inr": invested,
                "return_pct": return_pct,
                "xirr": xirr,
                "xirr_status": xirr_status,
                "day_change_inr": ex.get("day_change_inr"),
                "day_change_pct": ex.get("day_change_pct"),
                "latest_nav": latest_nav,
                "latest_nav_date": latest_nav_date,
                "has_transactions": bool(txns),
                "partial_history": partial_history,
                "partial_history_from": partial_from if partial_history else None,
                "integrity": integrity_rows,
                "folios": folios,
                "nav_history": nav_history,
                **dividend_detail,
                "corporate_actions": corporate_actions,
                "transactions": txns,
            }

    async def _value_series(
        self, session: AsyncSession, investor_ids: list[int], from_: date, to: date, granularity: str
    ) -> list[dict[str, Any]]:
        txn_keys, _hold_keys = await self._ledger_index(session, investor_ids)
        sec_ids = {k[0] for k in txn_keys}
        nav_idx = await self._nav_index(session, list(sec_ids), to)

        points: list[dict[str, Any]] = []
        for sample in _sample_dates(from_, to, granularity):
            agg = self._positions_asof(txn_keys, {}, sample)
            value = _ZERO
            invested = _ZERO
            stale = False
            for sec_id, (_sec, units, inv_amt) in agg.items():
                if units <= _ZERO:
                    continue
                invested += inv_amt
                price = self._price_at(nav_idx, sec_id, sample)
                if price is None:
                    stale = True
                    continue
                value += units * price
            points.append(
                {"date": sample, "value_inr": value, "invested_inr": invested, "stale": stale}
            )
        return points

    async def _series_from_stored(
        self, session: AsyncSession, investor_ids: list[int], from_: date, to: date, granularity: str
    ) -> list[dict[str, Any]]:
        stmt = (
            select(InvestorValue.date, InvestorValue.value_inr, InvestorValue.invested_inr)
            .where(
                InvestorValue.investor_id.in_(investor_ids),
                InvestorValue.date >= from_,
                InvestorValue.date <= to,
            )
            .order_by(InvestorValue.date)
        )
        rows = (await session.execute(stmt)).all()
        if not rows:
            # Fall back to live calculation if not pre-computed
            return await self._value_series(session, investor_ids, from_, to, granularity)

        by_date: dict[date, list[Decimal]] = {}
        for d, val, inv in rows:
            slot = by_date.setdefault(d, [_ZERO, _ZERO])
            slot[0] += val
            slot[1] += inv

        points = [
            {"date": d, "value_inr": v, "invested_inr": inv, "stale": False}
            for d, (v, inv) in sorted(by_date.items())
        ]
        return _downsample(points, granularity)

    async def value_series(
        self, investor_id: int, *, from_date: date | None = None, to_date: date | None = None, granularity: str = "monthly"
    ) -> dict[str, Any]:
        """Per-investor net-worth time series."""
        to = to_date or date.today()
        from_ = from_date or _add_months(to, -12)
        async with self.session_factory() as session:
            points = await self._series_from_stored(session, [investor_id], from_, to, granularity)
            return {
                "investor_id": investor_id,
                "start": from_,
                "end": to,
                "granularity": granularity,
                "points": points,
            }

    async def family_value_series(
        self, family_id: int, *, from_date: date | None = None, to_date: date | None = None, granularity: str = "monthly"
    ) -> dict[str, Any]:
        """Family aggregate net-worth time series."""
        to = to_date or date.today()
        from_ = from_date or _add_months(to, -12)
        async with self.session_factory() as session:
            stmt = select(Investor.id).where(Investor.family_id == family_id)
            member_ids = list((await session.execute(stmt)).scalars().all())
            points = await self._series_from_stored(session, member_ids, from_, to, granularity)
            return {
                "family_id": family_id,
                "start": from_,
                "end": to,
                "granularity": granularity,
                "points": points,
            }

    async def security_value_series(
        self, investor_id: int, security_id: int, *, to_date: date | None = None, granularity: str = "monthly"
    ) -> tuple[date, list[dict[str, Any]]]:
        """One holding's worth over time."""
        to = to_date or date.today()
        async with self.session_factory() as session:
            txn_keys, _hold = await self._ledger_index(session, [investor_id])
            filtered_keys = {k: v for k, v in txn_keys.items() if k[0] == security_id}
            if not filtered_keys:
                return to, []
            start = min(d for rec in filtered_keys.values() for (d, _core) in rec["core"])
            nav_idx = await self._nav_index(session, [security_id], to)
            points: list[dict[str, Any]] = []
            for sample in _sample_dates(start, to, granularity):
                agg = self._positions_asof(filtered_keys, {}, sample)
                value = invested = _ZERO
                stale = False
                for sid, (_sec, units, inv_amt) in agg.items():
                    if units <= _ZERO:
                        continue
                    invested += inv_amt
                    price = self._price_at(nav_idx, sid, sample)
                    if price is None:
                        stale = True
                        continue
                    value += units * price
                points.append(
                    {"date": sample, "value_inr": value, "invested_inr": invested, "stale": stale}
                )
            return start, points

    async def get_valuation_status(self, investor_id: int) -> dict[str, Any]:
        """Readiness status for an investor."""
        async with self.session_factory() as session:
            stmt = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt)).scalar_one_or_none()
            if inv is None:
                raise ValueError(f"Investor {investor_id} not found")

            stmt_prov = select(InvestorValue.id).where(
                InvestorValue.investor_id == investor_id, InvestorValue.is_provisional.is_(True)
            ).limit(1)
            is_provisional = (await session.execute(stmt_prov)).first() is not None

            return {
                "investor_id": inv.id,
                "status": inv.valuation_status,
                "computed_through": inv.valuation_computed_through,
                "recompute_from": inv.valuation_recompute_from,
                "is_provisional": is_provisional,
            }

    async def get_family_valuation_status(self, family_id: int) -> dict[str, Any]:
        """Readiness status for a family."""
        async with self.session_factory() as session:
            stmt = select(Investor.valuation_status, Investor.valuation_computed_through).where(
                Investor.family_id == family_id
            )
            statuses = (await session.execute(stmt)).all()
            states = {s[0] for s in statuses}
            if not states:
                status = "ready"
            elif states & {"pending", "computing"}:
                status = "computing"
            elif "error" in states:
                status = "error"
            else:
                status = "ready"
            throughs = [s[1] for s in statuses if s[1] is not None]

            stmt_prov = select(InvestorValue.id).join(Investor).where(
                Investor.family_id == family_id, InvestorValue.is_provisional.is_(True)
            ).limit(1)
            is_provisional = (await session.execute(stmt_prov)).first() is not None

            return {
                "family_id": family_id,
                "status": status,
                "computed_through": min(throughs) if throughs else None,
                "recompute_from": None,
                "is_provisional": is_provisional,
            }

    async def queue_recompute(
        self,
        investor_id: int,
        recompute_from: date,
        *,
        provisional_value: Decimal | None = None,
        provisional_invested: Decimal | None = None,
        as_of: date | None = None,
    ) -> None:
        """Mark investor for recomputation and optionally seed provisional value."""
        async with self.session_factory() as session:
            stmt = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt)).scalar_one_or_none()
            if inv is None:
                return

            existing = inv.valuation_recompute_from
            inv.valuation_recompute_from = min(existing, recompute_from) if existing else recompute_from
            inv.valuation_status = "computing"

            if as_of is not None and provisional_value is not None and provisional_value > _ZERO:
                stmt_v = select(InvestorValue).where(
                    InvestorValue.investor_id == investor_id, InvestorValue.date == as_of
                )
                iv = (await session.execute(stmt_v)).scalar_one_or_none()
                if iv:
                    iv.value_inr = provisional_value
                    iv.invested_inr = provisional_invested or _ZERO
                    iv.is_provisional = True
                else:
                    session.add(
                        InvestorValue(
                            investor_id=investor_id,
                            date=as_of,
                            value_inr=provisional_value,
                            invested_inr=provisional_invested or _ZERO,
                            is_provisional=True,
                        )
                    )
            await session.commit()

    async def _earliest_activity(self, session: AsyncSession, investor_id: int) -> date | None:
        stmt_t = select(func.min(Transaction.date)).where(
            Transaction.investor_id == investor_id, Transaction.cost_basis_complete.is_(True)
        )
        t_min = await session.scalar(stmt_t)
        stmt_h = select(func.min(Holding.as_of_date)).where(Holding.investor_id == investor_id)
        h_min = await session.scalar(stmt_h)
        dates = [d for d in (t_min, h_min) if d is not None]
        return min(dates) if dates else None

    async def _upsert_series(self, session: AsyncSession, investor_id: int, points: list[dict[str, Any]]) -> None:
        """Upsert daily points into InvestorValue."""
        if not points:
            return
        dates = [p["date"] for p in points]
        stmt = select(InvestorValue).where(
            InvestorValue.investor_id == investor_id, InvestorValue.date.in_(dates)
        )
        existing_rows = {iv.date: iv for iv in (await session.execute(stmt)).scalars().all()}

        for p in points:
            d = p["date"]
            if d in existing_rows:
                row = existing_rows[d]
                row.value_inr = p["value_inr"]
                row.invested_inr = p["invested_inr"]
                row.is_provisional = False
            else:
                session.add(
                    InvestorValue(
                        investor_id=investor_id,
                        date=d,
                        value_inr=p["value_inr"],
                        invested_inr=p["invested_inr"],
                        is_provisional=False,
                    )
                )

    async def recompute_investor_valuation(
        self, investor_id: int, from_date: date | None = None, *, prime_navs: bool = True
    ) -> str:
        """Recompute daily InvestorValue series from from_date (or start) to today."""
        async with self.session_factory() as session:
            stmt = select(Investor).where(Investor.id == investor_id)
            inv = (await session.execute(stmt)).scalar_one_or_none()
            if inv is None:
                return "missing"

            today = date.today()
            start = from_date or inv.valuation_recompute_from or inv.valuation_computed_through or await self._earliest_activity(session, investor_id)
            if start is None:
                inv.valuation_status = "ready"
                inv.valuation_computed_through = today
                inv.valuation_recompute_from = None
                await session.commit()
                return "ready"

            inv.valuation_status = "computing"
            await session.commit()

        try:
            if prime_navs:
                await self._nav_service.refresh_navs()

            async with self.session_factory() as session:
                points = await self._value_series(session, [investor_id], start, today, "daily")
                await self._upsert_series(session, investor_id, points)

                stmt = select(Investor).where(Investor.id == investor_id)
                inv = (await session.execute(stmt)).scalar_one()
                inv.valuation_status = "ready"
                inv.valuation_computed_through = today
                inv.valuation_recompute_from = None
                inv.valuation_attempts = 0
                inv.valuation_error = ""
                inv.valuation_next_attempt_at = None
                await session.commit()
            return "ready"
        except Exception as exc:
            async with self.session_factory() as session:
                stmt = select(Investor).where(Investor.id == investor_id)
                inv = (await session.execute(stmt)).scalar_one_or_none()
                if inv:
                    inv.valuation_status = "error"
                    inv.valuation_attempts = (inv.valuation_attempts or 0) + 1
                    inv.valuation_error = str(exc)[:500]
                    if inv.valuation_attempts < _MAX_ATTEMPTS:
                        inv.valuation_next_attempt_at = datetime.now(timezone.utc) + _backoff(inv.valuation_attempts)
                    else:
                        inv.valuation_next_attempt_at = None
                    await session.commit()
            return "error"

    async def process_pending_valuations(self) -> int:
        """Process all investors that are pending/computing or due for retry."""
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            stmt = select(Investor.id, Investor.valuation_recompute_from).where(
                (Investor.valuation_status.in_(["pending", "computing"]))
                | (
                    (Investor.valuation_status == "error")
                    & (Investor.valuation_next_attempt_at.is_not(None))
                    & (Investor.valuation_next_attempt_at <= now)
                )
            )
            due = list((await session.execute(stmt)).all())

        if not due:
            return 0

        # Prime NAVs once for all
        await self._nav_service.refresh_navs()
        processed = 0
        for iid, r_from in due:
            await self.recompute_investor_valuation(iid, r_from, prime_navs=False)
            processed += 1
        return processed

    async def enqueue_daily_extend(self) -> int:
        """Re-queue every ready and error investor for daily extension."""
        async with self.session_factory() as session:
            # Ready investors: set pending and recompute_from = computed_through
            stmt_ready = (
                update(Investor)
                .where(Investor.valuation_status == "ready")
                .values(
                    valuation_status="pending",
                    valuation_recompute_from=Investor.valuation_computed_through,
                )
            )
            res_ready = await session.execute(stmt_ready)

            # Error investors: retry
            stmt_err = (
                update(Investor)
                .where(Investor.valuation_status == "error")
                .values(
                    valuation_status="pending",
                    valuation_attempts=0,
                    valuation_next_attempt_at=None,
                )
            )
            res_err = await session.execute(stmt_err)
            await session.commit()
            return res_ready.rowcount + res_err.rowcount

    async def enqueue_catch_up_if_stale(self) -> int:
        """Launch-time catch-up if valuation or NAVs are stale."""
        today = date.today()
        async with self.session_factory() as session:
            stmt = select(Investor.id).where(
                Investor.valuation_status == "ready",
                (Investor.valuation_computed_through.is_(None))
                | (Investor.valuation_computed_through < today),
            ).limit(1)
            behind = (await session.execute(stmt)).first() is not None

            stmt_all_inv = select(Investor.id)
            all_iids = list((await session.execute(stmt_all_inv)).scalars().all())
            navs_as_of = await self._book_navs_as_of(session, all_iids, today)
            stale = self._navs_stale(navs_as_of, today)

        if behind or stale:
            return await self.enqueue_daily_extend()
        return 0


__all__ = [
    "ValuationService",
]
